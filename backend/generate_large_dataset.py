# generate_large_dataset.py
"""
Script to generate large synthetic CSV datasets for benchmarking and load testing.
Supports custom row counts and outputs directly to a local CSV file.

Usage:
    python generate_large_dataset.py --rows 100000 --output large_sales_data.csv
"""

import csv
import random
import argparse
import time
from datetime import datetime, timedelta

CATEGORIES = ["Electronics", "Apparel", "Home & Kitchen", "Automotive", "Sports & Outdoors", "Books", "Toys"]
STATUSES = ["Completed", "Pending", "Refunded", "Failed"]
STATES = ["NY", "CA", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI", "WA", "AZ", "CO", "MA"]

def generate_dataset(num_rows, output_path):
    print(f"[*] Starting generation of {num_rows:,} rows of synthetic data...")
    start_time = time.time()
    
    headers = [
        "transaction_id", 
        "timestamp", 
        "customer_id", 
        "product_category", 
        "amount", 
        "status", 
        "state"
    ]
    
    base_date = datetime.now() - timedelta(days=365)
    
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        for i in range(1, num_rows + 1):
            tx_id = 10000000 + i
            # Increment timestamp slightly per row to simulate steady stream over the year
            seconds_offset = random.randint(0, 31536000)
            timestamp = (base_date + timedelta(seconds=seconds_offset)).isoformat(sep=" ", timespec="seconds")
            cust_id = random.randint(10000, 99999)
            category = random.choice(CATEGORIES)
            amount = round(random.uniform(5.99, 1499.99), 2)
            status = random.choice(STATUSES)
            state = random.choice(STATES)
            
            writer.writerow([tx_id, timestamp, cust_id, category, amount, status, state])
            
            if i % 100000 == 0:
                print(f"[-] Generated {i:,} rows...")
                
    elapsed_time = time.time() - start_time
    print(f"[+] Successfully generated and saved {num_rows:,} rows to: {output_path}")
    print(f"[+] Total elapsed time: {elapsed_time:.2f} seconds")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate large synthetic CSV data for testing.")
    parser.add_argument("--rows", type=int, default=10000, help="Number of rows to generate (default: 10000)")
    parser.add_argument("--output", type=str, default="synthetic_transactions.csv", help="Output CSV path (default: synthetic_transactions.csv)")
    
    args = parser.parse_args()
    generate_dataset(args.rows, args.output)
