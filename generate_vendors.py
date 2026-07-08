# generate_vendors.py
import csv
import random
from datetime import datetime, timedelta

def generate_vendors_csv(num_rows, output_path):
    print(f"Generating {num_rows} vendor rows with 50 columns...")
    
    headers = [
        "vendor_id", "vendor_name", "category", "country", "status", 
        "contract_date", "compliance_rating", "annual_spend", "contact_email", "contact_phone",
        "address", "city", "state", "postal_code", "payment_terms", 
        "tax_id", "bank_account", "routing_number", "is_active", "primary_contact",
        "website", "credit_limit", "risk_score", "insurance_status", "nda_signed",
        "diversity_certified", "preferred_status", "last_audit_date", "next_review_date", "sailing_terms",
        "currency", "duns_number", "parent_company", "employee_count", "year_founded",
        "security_rating", "data_protection_certified", "esg_score", "sla_compliance_rate", "delivery_lead_time_days",
        "defect_rate_pct", "invoicing_method", "discount_pct", "freight_terms", "origin_port",
        "backup_vendor_id", "account_manager", "notes", "created_at", "updated_at"
    ]
    
    categories = ["IT Hardware", "Software Licensing", "Office Supplies", "Logistics", "Professional Services", "Marketing Agencies", "Manufacturing Raw Materials", "Facilities Management"]
    countries = ["US", "CA", "GB", "DE", "FR", "JP", "IN", "AU", "BR", "MX"]
    statuses = ["Approved", "Under Review", "On Hold", "Suspended"]
    payment_terms = ["NET30", "NET45", "NET60", "2/10 NET30", "Immediate"]
    insurance_statuses = ["Fully Insured", "Expired", "Not Required", "Pending Verification"]
    preferred_statuses = ["Tier 1 Preferred", "Tier 2 Approved", "Specialty Vendor", "Ad-hoc Vendor"]
    invoicing_methods = ["EDI Portal", "Email PDF", "Mail paper", "Ariba Network"]
    freight_terms = ["FOB Destination", "FOB Shipping Point", "EXW", "CIF", "DDP"]
    currencies = ["USD", "EUR", "GBP", "CAD", "JPY", "INR"]
    managers = ["Sarah Jenkins", "Michael Chang", "Amanda Ross", "David Miller", "Jessica Taylor", "Robert Patel"]
    
    base_date = datetime.now() - timedelta(days=730)
    
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        for i in range(1, num_rows + 1):
            v_id = 200000 + i
            v_name = f"Global Vendor {i} Inc."
            cat = random.choice(categories)
            country = random.choice(countries)
            status = random.choice(statuses)
            
            contract_days = random.randint(0, 730)
            contract_date = (base_date + timedelta(days=contract_days)).strftime("%Y-%m-%d")
            
            compliance = random.randint(50, 100)
            annual_spend = round(random.uniform(5000.0, 2500000.0), 2)
            email = f"contact@vendor{i}.com"
            phone = f"+1-{random.randint(200,999)}-555-{random.randint(1000,9999)}"
            address = f"{random.randint(100,9999)} Commerce Blvd Suite {random.randint(1,100)}"
            city = f"Industrial City {random.randint(1,50)}"
            state = random.choice(["CA", "NY", "TX", "FL", "IL", "OH", "WA", "MA", "ON", "QC"])
            postal = f"{random.randint(10000,99999)}"
            p_terms = random.choice(payment_terms)
            
            tax_id = f"XX-{random.randint(1000000,9999999)}"
            bank = f"BANK-{random.randint(10000000,99999999)}"
            routing = f"ROUT-{random.randint(10000000,99999999)}"
            is_active = random.choice([True, True, True, False])
            contact_person = f"Contact Manager {i}"
            
            web = f"https://www.vendor{i}.com"
            limit = round(random.uniform(10000.0, 500000.0), 2)
            risk = random.randint(1, 10)
            insurance = random.choice(insurance_statuses)
            nda = random.choice([True, True, False])
            diversity = random.choice([True, False, False])
            preferred = random.choice(preferred_statuses)
            
            last_audit = (base_date + timedelta(days=random.randint(0,365))).strftime("%Y-%m-%d")
            next_review = (datetime.now() + timedelta(days=random.randint(30,365))).strftime("%Y-%m-%d")
            sailing = random.choice(["FOB", "CIF", "DAP", "EXW"])
            currency = random.choice(currencies)
            duns = f"{random.randint(100000000,999999999)}"
            parent = f"Vendor Parent Group {random.randint(1,100)}"
            employees = random.randint(10, 5000)
            year_founded = random.randint(1950, 2024)
            security = random.randint(1, 100)
            gdpr = random.choice([True, False])
            esg = random.randint(1, 100)
            sla = round(random.uniform(85.0, 100.0), 2)
            lead_time = random.randint(1, 60)
            defect_rate = round(random.uniform(0.0, 5.0), 3)
            invoice_m = random.choice(invoicing_methods)
            discount = round(random.uniform(0.0, 10.0), 2)
            freight = random.choice(freight_terms)
            port = f"Port of {random.choice(['Long Beach', 'Rotterdam', 'Shanghai', 'Hamburg', 'Singapore'])}"
            backup_id = random.randint(200001, 210000)
            manager = random.choice(managers)
            notes = f"Standard vendor agreement for category {cat}. Verified on {contract_date}."
            
            created = (base_date + timedelta(days=contract_days)).isoformat(timespec="seconds")
            updated = datetime.now().isoformat(timespec="seconds")
            
            writer.writerow([
                v_id, v_name, cat, country, status, 
                contract_date, compliance, annual_spend, email, phone,
                address, city, state, postal, p_terms, 
                tax_id, bank, routing, is_active, contact_person,
                web, limit, risk, insurance, nda,
                diversity, preferred, last_audit, next_review, sailing,
                currency, duns, parent, employees, year_founded,
                security, gdpr, esg, sla, lead_time,
                defect_rate, invoice_m, discount, freight, port,
                backup_id, manager, notes, created, updated
            ])
            
    print(f"Successfully generated 10k rows and 50 columns to: {output_path}")

if __name__ == "__main__":
    generate_vendors_csv(10000, "vendors_10k_50col.csv")
