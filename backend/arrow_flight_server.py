import os
import sys
import json
import pyarrow as pa
import pyarrow.flight as flight

# Add parent dir to resolve imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalog_setup import get_catalog

class meldraFlightServer(flight.FlightServerBase):
    def __init__(self, host="0.0.0.0", port=8888, **kwargs):
        location = f"grpc+tcp://{host}:{port}"
        super(meldraFlightServer, self).__init__(location, **kwargs)
        self.location = location
        self.catalog = get_catalog()

    def _parse_ticket(self, ticket_bytes):
        try:
            return json.loads(ticket_bytes.decode('utf-8'))
        except Exception:
            return {"namespace": "default", "table": ticket_bytes.decode('utf-8')}

    def get_flight_info(self, context, descriptor):
        table_info = {}
        if descriptor.descriptor_type == flight.DescriptorType.PATH:
            path = [p.decode('utf-8') for p in descriptor.path]
            if len(path) >= 2:
                table_info = {"namespace": path[0], "table": path[1]}
            else:
                table_info = {"namespace": "default", "table": path[0]}
        else:
            try:
                table_info = json.loads(descriptor.command.decode('utf-8'))
            except Exception:
                table_info = {"namespace": "default", "table": descriptor.command.decode('utf-8')}

        namespace = table_info.get("namespace", "default")
        table_name = table_info.get("table")
        
        table_identifier = f"{namespace}.{table_name}"
        table = self.catalog.load_table(table_identifier)
        arrow_schema = table.scan().to_arrow().schema

        endpoints = [
            flight.FlightEndpoint(descriptor.command or b"", [self.location])
        ]
        return flight.FlightInfo(
            arrow_schema,
            descriptor,
            endpoints,
            -1,
            -1
        )

    def do_get(self, context, ticket):
        info = self._parse_ticket(ticket.ticket)
        namespace = info.get("namespace", "default")
        table_name = info.get("table")

        table_identifier = f"{namespace}.{table_name}"
        table = self.catalog.load_table(table_identifier)
        arrow_table = table.scan().to_arrow()

        return flight.RecordBatchStream(arrow_table)

    def list_flights(self, context, criteria):
        flights = []
        try:
            tables = self.catalog.list_tables("default")
            for t_ident in tables:
                namespace, name = t_ident
                descriptor = flight.FlightDescriptor.for_path(namespace, name)
                
                table = self.catalog.load_table(f"{namespace}.{name}")
                schema = table.scan().to_arrow().schema
                
                endpoints = [flight.FlightEndpoint(f"{namespace}.{name}", [self.location])]
                flights.append(flight.FlightInfo(schema, descriptor, endpoints, -1, -1))
        except Exception as e:
            print(f"[FlightServer] list_flights error: {e}")
        return flights

def start_server(host="0.0.0.0", port=8888):
    server = meldraFlightServer(host, port)
    print(f"[FlightServer] Listening on grpc+tcp://{host}:{port}")
    server.serve()

if __name__ == "__main__":
    start_server()
