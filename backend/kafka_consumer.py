"""
kafka_consumer.py — Real-time Kafka consumer for Apache Iceberg.
Consumes messages from a Kafka topic and writes them to an Iceberg table on S3/ADLS Gen2.
Supports --dry-run / mock mode for developer testing.
"""
import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("kafka_consumer")

# Add parent directory to path to resolve local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import pyarrow as pa
    from catalog_setup import get_catalog
except ImportError as e:
    logger.error("Failed to import required libraries (pyarrow or catalog_setup): %s", e)
    sys.exit(1)

# Optional confluent-kafka import
try:
    from confluent_kafka import Consumer, KafkaError, KafkaException
    KAFKA_AVAILABLE = True
except ImportError:
    logger.warning("confluent_kafka not installed. Live consumer mode will be unavailable. Run: pip install confluent-kafka")
    KAFKA_AVAILABLE = False


def process_batch(records: list, namespace: str, table_name: str, catalog) -> int:
    """Convert batch of dict records to PyArrow and append to Iceberg table."""
    if not records:
        return 0

    try:
        # Load Iceberg table and schema
        identifier = f"{namespace}.{table_name}"
        table = catalog.load_table(identifier)
        pyarrow_schema = table.schema().as_arrow()

        # Convert list of dicts to PyArrow table
        pydict = {}
        for field in pyarrow_schema:
            pydict[field.name] = []

        for rec in records:
            for field in pyarrow_schema:
                val = rec.get(field.name)
                pydict[field.name].append(val)

        arrow_table = pa.Table.from_pydict(pydict, schema=pyarrow_schema)

        # Append data to the Iceberg table
        table.append(arrow_table)
        logger.info("Successfully committed %d records to Iceberg table %s", len(records), identifier)
        return len(records)

    except Exception as e:
        logger.error("Failed to commit batch to Iceberg: %s", e)
        raise e


def run_mock_consumer(namespace: str, table_name: str, dry_run: bool):
    """Simulate a Kafka stream generating mock transactions."""
    logger.info("Starting MOCK consumer on topic 'mock-payment-transactions'...")
    catalog = get_catalog() if not dry_run else None

    # Generate mock transaction data
    import random
    mock_id = 90001
    
    try:
        while True:
            # Generate a batch of mock transactions
            batch_size = random.randint(2, 5)
            records = []
            for _ in range(batch_size):
                rec = {
                    "tx_id": mock_id,
                    "account_from": f"ACC-{random.randint(100, 200):03d}",
                    "account_to": f"ACC-{random.randint(200, 300):03d}",
                    "amount": round(random.uniform(5.0, 1500.0), 2),
                    "status": random.choice(["COMPLETED", "COMPLETED", "PENDING", "FAILED"]),
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
                records.append(rec)
                mock_id += 1

            logger.info("Received mock batch of %d records from Kafka stream", len(records))
            
            if dry_run:
                logger.info("[DRY RUN] Would write records: %s", json.dumps(records, indent=2))
            else:
                process_batch(records, namespace, table_name, catalog)

            # Wait before generating next batch
            time.sleep(3.0)

    except KeyboardInterrupt:
        logger.info("Mock consumer stopped by user.")


def run_live_consumer(bootstrap_servers: str, group_id: str, topic: str, namespace: str, table_name: str):
    """Run production confluent-kafka consumer loop."""
    if not KAFKA_AVAILABLE:
        logger.error("Cannot run live consumer because confluent_kafka is not installed.")
        sys.exit(1)

    conf = {
        'bootstrap.servers': bootstrap_servers,
        'group.id': group_id,
        'auto.offset.reset': 'smallest',
        'enable.auto.commit': False
    }

    try:
        consumer = Consumer(conf)
        consumer.subscribe([topic])
        logger.info("Subscribed to live Kafka topic '%s' on %s", topic, bootstrap_servers)
        
        catalog = get_catalog()
        batch = []
        batch_timeout = 2.0  # seconds
        last_flush = time.time()
        max_batch_size = 100

        while True:
            msg = consumer.poll(timeout=0.5)

            if msg is None:
                # Flush batch on timeout
                if batch and (time.time() - last_flush > batch_timeout):
                    process_batch(batch, namespace, table_name, catalog)
                    consumer.commit()
                    batch = []
                    last_flush = time.time()
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logger.error("Kafka error: %s", msg.error())
                    raise KafkaException(msg.error())

            try:
                payload = json.loads(msg.value().decode('utf-8'))
                batch.append(payload)
            except Exception as pe:
                logger.warning("Failed to parse Kafka message JSON: %s", pe)

            if len(batch) >= max_batch_size or (time.time() - last_flush > batch_timeout):
                if batch:
                    process_batch(batch, namespace, table_name, catalog)
                    consumer.commit()
                    batch = []
                    last_flush = time.time()

    except KeyboardInterrupt:
        logger.info("Live consumer shutdown initiated.")
    finally:
        if 'consumer' in locals():
            consumer.close()
            logger.info("Kafka consumer closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meldra real-time Kafka-to-Iceberg consumer")
    parser.add_argument("--bootstrap-servers", default="localhost:9092", help="Kafka broker bootstrap servers")
    parser.add_argument("--group-id", default="iceberg-ingest-group", help="Kafka consumer group ID")
    parser.add_argument("--topic", default="payment-transactions", help="Kafka topic to consume from")
    parser.add_argument("--namespace", default="default", help="Iceberg catalog namespace")
    parser.add_argument("--table", default="transactions_10k", help="Iceberg table name")
    parser.add_argument("--mock", action="store_true", help="Run with mock generator stream instead of live Kafka")
    parser.add_argument("--dry-run", action="store_true", help="Print batches without committing to Iceberg")

    args = parser.parse_args()

    logger.info("Meldra Ingestion Service Initializing...")
    logger.info("Target Table: %s.%s", args.namespace, args.table)
    if args.dry_run:
        logger.info("Mode: DRY-RUN (no commits will be made to S3)")

    if args.mock or not KAFKA_AVAILABLE:
        run_mock_consumer(args.namespace, args.table, args.dry_run)
    else:
        run_live_consumer(args.bootstrap_servers, args.group_id, args.topic, args.namespace, args.table)
