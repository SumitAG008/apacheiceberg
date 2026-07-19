import os
import sys
import pandas as pd
import numpy as np
import pyarrow as pa
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, IntegerType, StringType, DoubleType, BooleanType, LongType

# Insert backend path to resolve local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalog_setup import get_catalog, create_namespace_if_not_exists

def generate_and_ingest():
    # 1. Generate 150 rows of data
    np.random.seed(42)
    n_rows = 150
    
    countries = ["United Kingdom", "United States", "Germany", "France", "Japan", "Canada", "Australia", "India"]
    facility_names = [f"Facility-{chr(65 + (i % 26))}{i}" for i in range(n_rows)]
    contractors = [f"Contractor-{i % 15 + 1}" for i in range(n_rows)]
    esg_grades = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]
    audit_firms = ["KPMG", "PwC", "Deloitte", "EY"]
    
    # Base columns
    record_ids = list(range(1, n_rows + 1))
    fac_names = [facility_names[i] for i in range(n_rows)]
    fac_countries = [countries[np.random.randint(0, len(countries))] for _ in range(n_rows)]
    years = [np.random.choice([2024, 2025, 2026]) for _ in range(n_rows)]
    quarters = [f"Q{np.random.randint(1, 5)}" for _ in range(n_rows)]
    
    # Emissions (Scope 1, 2, 3)
    scope1 = np.round(np.random.uniform(100.0, 5000.0, n_rows), 2)
    scope2 = np.round(np.random.uniform(50.0, 3000.0, n_rows), 2)
    scope3 = np.round(np.random.uniform(500.0, 20000.0, n_rows), 2)
    biogenic = np.round(np.random.uniform(0.0, 500.0, n_rows), 2)
    ch4 = np.round(np.random.uniform(0.1, 10.0, n_rows), 2)
    n2o = np.round(np.random.uniform(0.01, 2.0, n_rows), 2)
    hfcs = np.round(np.random.uniform(0.0, 5.0, n_rows), 2)
    
    # GHG calc (Scope 1 + 2 + 3 + biogenic)
    total_ghg = np.round(scope1 + scope2 + scope3 + biogenic, 2)
    carbon_intensity = np.round(total_ghg / np.random.uniform(10.0, 100.0, n_rows), 4)
    
    # Energy
    energy_mwh = np.round(np.random.uniform(1000.0, 50000.0, n_rows), 2)
    renewable_mwh = np.round(energy_mwh * np.random.uniform(0.1, 0.9, n_rows), 2)
    renewable_share = np.round((renewable_mwh / energy_mwh) * 100, 2)
    
    # Water & Waste
    water_withdrawal = np.round(np.random.uniform(500.0, 25000.0, n_rows), 2)
    water_consumption = np.round(water_withdrawal * np.random.uniform(0.6, 0.9, n_rows), 2)
    hazardous_waste = np.round(np.random.uniform(1.0, 50.0, n_rows), 2)
    non_hazardous_waste = np.round(np.random.uniform(10.0, 1000.0, n_rows), 2)
    recycled_waste = np.round(non_hazardous_waste * np.random.uniform(0.3, 0.8, n_rows), 2)
    recycling_rate = np.round((recycled_waste / non_hazardous_waste) * 100, 2)
    
    # Targets
    has_net_zero = [bool(np.random.choice([True, False])) for _ in range(n_rows)]
    net_zero_year = [int(np.random.choice([2030, 2035, 2040, 2045, 2050])) if has_net_zero[i] else 0 for i in range(n_rows)]
    sbti_approved = [bool(np.random.choice([True, False])) if has_net_zero[i] else False for i in range(n_rows)]
    
    # ESG scores
    esg_env = np.round(np.random.uniform(60.0, 98.0, n_rows), 1)
    esg_soc = np.round(np.random.uniform(50.0, 95.0, n_rows), 1)
    esg_gov = np.round(np.random.uniform(55.0, 96.0, n_rows), 1)
    total_esg = np.round((esg_env * 0.4 + esg_soc * 0.3 + esg_gov * 0.3), 1)
    esg_grade = [esg_grades[int(np.clip((100 - total_esg[i]) / 6, 0, len(esg_grades)-1))] for i in range(n_rows)]
    
    # Contractors
    contractor_ids = [f"CNT-{100 + (i % 15):03d}" for i in range(n_rows)]
    contractor_names = [contractors[i] for i in range(n_rows)]
    contractor_emissions = np.round(scope3 * np.random.uniform(0.1, 0.4, n_rows), 2)
    contractor_compliance = [np.random.choice(["Compliant", "Compliant", "Under Review", "Non-Compliant"]) for _ in range(n_rows)]
    
    # Incidents & Spills
    incidents = [int(np.random.choice([0, 0, 0, 1, 2])) for _ in range(n_rows)]
    spills = [int(np.random.choice([0, 0, 0, 0, 1])) if incidents[i] > 0 else 0 for i in range(n_rows)]
    spills_vol = [np.round(np.random.uniform(5.0, 200.0), 2) if spills[i] > 0 else 0.0 for i in range(n_rows)]
    
    # Initiatives & compliance
    reduction_initiatives = [int(np.random.randint(1, 8)) for _ in range(n_rows)]
    ghg_proto_compliant = [bool(np.random.choice([True, True, False])) for _ in range(n_rows)]
    audit_firm = [audit_firms[np.random.randint(0, len(audit_firms))] for _ in range(n_rows)]
    last_audit_date = [f"2025-{np.random.randint(1, 13):02d}-{np.random.randint(1, 28):02d}" for _ in range(n_rows)]
    
    # Capex / Financials
    carbon_tax = np.round(scope1 * 25.0 * np.random.uniform(0.8, 1.2, n_rows), 2)
    fines = np.round([float(np.random.uniform(1000.0, 25000.0)) if incidents[i] > 1 else 0.0 for i in range(n_rows)], 2)
    green_bond = np.round([float(np.random.choice([0.0, 0.0, 100000.0, 500000.0, 1500000.0])) for _ in range(n_rows)], 2)
    energy_capex = np.round(np.random.uniform(10000.0, 300000.0, n_rows), 2)
    rd_capex = np.round(np.random.uniform(5000.0, 150000.0, n_rows), 2)
    
    # Extra Climate Metrics
    temp_deviation = np.round(np.random.uniform(0.5, 2.5, n_rows), 2)
    climate_vulnerability = np.round(np.random.uniform(0.1, 0.85, n_rows), 3)
    aqi_pm25 = np.round(np.random.uniform(5.0, 120.0, n_rows), 1)
    
    # 51st Column
    mitigation_target = np.round(np.random.uniform(5.0, 95.0, n_rows), 2)
    
    data_dict = {
        "record_id": record_ids,
        "facility_name": fac_names,
        "facility_country": fac_countries,
        "reporting_year": years,
        "reporting_quarter": quarters,
        "scope_1_emissions_mt": scope1,
        "scope_2_emissions_mt": scope2,
        "scope_3_emissions_mt": scope3,
        "biogenic_co2_emissions_mt": biogenic,
        "ch4_emissions_mt": ch4,
        "n2o_emissions_mt": n2o,
        "hfcs_emissions_mt": hfcs,
        "total_ghg_emissions_co2e_mt": total_ghg,
        "carbon_intensity_per_revenue": carbon_intensity,
        "energy_consumption_mwh": energy_mwh,
        "renewable_energy_consumption_mwh": renewable_mwh,
        "renewable_energy_share_pct": renewable_share,
        "water_withdrawal_cubic_meters": water_withdrawal,
        "water_consumption_cubic_meters": water_consumption,
        "hazardous_waste_generated_tons": hazardous_waste,
        "non_hazardous_waste_generated_tons": non_hazardous_waste,
        "waste_recycled_tons": recycled_waste,
        "waste_recycling_rate_pct": recycling_rate,
        "has_net_zero_target": has_net_zero,
        "net_zero_target_year": net_zero_year,
        "sbti_approved_target": sbti_approved,
        "esg_score_environmental": esg_env,
        "esg_score_social": esg_soc,
        "esg_score_governance": esg_gov,
        "total_esg_score": total_esg,
        "esg_rating_grade": esg_grade,
        "contractor_id": contractor_ids,
        "contractor_name": contractor_names,
        "contractor_emissions_scope3_mt": contractor_emissions,
        "contractor_compliance_status": contractor_compliance,
        "environmental_incidents_count": incidents,
        "spills_count": spills,
        "spills_volume_liters": spills_vol,
        "ghg_reduction_initiatives_count": reduction_initiatives,
        "greenhouse_gas_protocol_compliant": ghg_proto_compliant,
        "audit_firm_audited": audit_firm,
        "last_audit_date": last_audit_date,
        "carbon_tax_paid_usd": carbon_tax,
        "environmental_fines_paid_usd": fines,
        "green_bond_funding_received_usd": green_bond,
        "energy_efficiency_capex_usd": energy_capex,
        "r_and_d_clean_tech_capex_usd": rd_capex,
        "average_temperature_deviation_c": temp_deviation,
        "climate_risk_vulnerability_index": climate_vulnerability,
        "air_quality_index_pm25": aqi_pm25,
        "climate_mitigation_target_pct": mitigation_target,
    }
    
    df = pd.DataFrame(data_dict)
    
    # Save CSV
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    csv_path = os.path.join(data_dir, "climate_esg_analytics.csv")
    df.to_csv(csv_path, index=False)
    print(f"Generated Climate ESG dataset with {df.shape[0]} rows and {df.shape[1]} columns at: {csv_path}")
    
    # 2. Ingest to Iceberg Catalog
    catalog = get_catalog()
    create_namespace_if_not_exists(catalog, "default")
    
    # Build schema fields
    schema = Schema(
        NestedField(field_id=1, name="record_id", field_type=LongType(), required=True),
        NestedField(field_id=2, name="facility_name", field_type=StringType(), required=False),
        NestedField(field_id=3, name="facility_country", field_type=StringType(), required=False),
        NestedField(field_id=4, name="reporting_year", field_type=IntegerType(), required=False),
        NestedField(field_id=5, name="reporting_quarter", field_type=StringType(), required=False),
        NestedField(field_id=6, name="scope_1_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=7, name="scope_2_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=8, name="scope_3_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=9, name="biogenic_co2_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=10, name="ch4_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=11, name="n2o_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=12, name="hfcs_emissions_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=13, name="total_ghg_emissions_co2e_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=14, name="carbon_intensity_per_revenue", field_type=DoubleType(), required=False),
        NestedField(field_id=15, name="energy_consumption_mwh", field_type=DoubleType(), required=False),
        NestedField(field_id=16, name="renewable_energy_consumption_mwh", field_type=DoubleType(), required=False),
        NestedField(field_id=17, name="renewable_energy_share_pct", field_type=DoubleType(), required=False),
        NestedField(field_id=18, name="water_withdrawal_cubic_meters", field_type=DoubleType(), required=False),
        NestedField(field_id=19, name="water_consumption_cubic_meters", field_type=DoubleType(), required=False),
        NestedField(field_id=20, name="hazardous_waste_generated_tons", field_type=DoubleType(), required=False),
        NestedField(field_id=21, name="non_hazardous_waste_generated_tons", field_type=DoubleType(), required=False),
        NestedField(field_id=22, name="waste_recycled_tons", field_type=DoubleType(), required=False),
        NestedField(field_id=23, name="waste_recycling_rate_pct", field_type=DoubleType(), required=False),
        NestedField(field_id=24, name="has_net_zero_target", field_type=BooleanType(), required=False),
        NestedField(field_id=25, name="net_zero_target_year", field_type=IntegerType(), required=False),
        NestedField(field_id=26, name="sbti_approved_target", field_type=BooleanType(), required=False),
        NestedField(field_id=27, name="esg_score_environmental", field_type=DoubleType(), required=False),
        NestedField(field_id=28, name="esg_score_social", field_type=DoubleType(), required=False),
        NestedField(field_id=29, name="esg_score_governance", field_type=DoubleType(), required=False),
        NestedField(field_id=30, name="total_esg_score", field_type=DoubleType(), required=False),
        NestedField(field_id=31, name="esg_rating_grade", field_type=StringType(), required=False),
        NestedField(field_id=32, name="contractor_id", field_type=StringType(), required=False),
        NestedField(field_id=33, name="contractor_name", field_type=StringType(), required=False),
        NestedField(field_id=34, name="contractor_emissions_scope3_mt", field_type=DoubleType(), required=False),
        NestedField(field_id=35, name="contractor_compliance_status", field_type=StringType(), required=False),
        NestedField(field_id=36, name="environmental_incidents_count", field_type=IntegerType(), required=False),
        NestedField(field_id=37, name="spills_count", field_type=IntegerType(), required=False),
        NestedField(field_id=38, name="spills_volume_liters", field_type=DoubleType(), required=False),
        NestedField(field_id=39, name="ghg_reduction_initiatives_count", field_type=IntegerType(), required=False),
        NestedField(field_id=40, name="greenhouse_gas_protocol_compliant", field_type=BooleanType(), required=False),
        NestedField(field_id=41, name="audit_firm_audited", field_type=StringType(), required=False),
        NestedField(field_id=42, name="last_audit_date", field_type=StringType(), required=False),
        NestedField(field_id=43, name="carbon_tax_paid_usd", field_type=DoubleType(), required=False),
        NestedField(field_id=44, name="environmental_fines_paid_usd", field_type=DoubleType(), required=False),
        NestedField(field_id=45, name="green_bond_funding_received_usd", field_type=DoubleType(), required=False),
        NestedField(field_id=46, name="energy_efficiency_capex_usd", field_type=DoubleType(), required=False),
        NestedField(field_id=47, name="r_and_d_clean_tech_capex_usd", field_type=DoubleType(), required=False),
        NestedField(field_id=48, name="average_temperature_deviation_c", field_type=DoubleType(), required=False),
        NestedField(field_id=49, name="climate_risk_vulnerability_index", field_type=DoubleType(), required=False),
        NestedField(field_id=50, name="air_quality_index_pm25", field_type=DoubleType(), required=False),
        NestedField(field_id=51, name="climate_mitigation_target_pct", field_type=DoubleType(), required=False)
    )
    
    identifier = ("default", "climate_esg_analytics")
    
    table_exists = False
    try:
        catalog.load_table(identifier)
        table_exists = True
        print(f"Iceberg table '{identifier[0]}.{identifier[1]}' already exists. Overwriting with new data.")
    except Exception:
        pass
        
    if not table_exists:
        print(f"Creating new Iceberg table '{identifier[0]}.{identifier[1]}'...")
        table = catalog.create_table(identifier, schema=schema)
    else:
        table = catalog.load_table(identifier)
        
    # Cast df columns explicitly to match schema types for PyArrow
    arrow_table = pa.Table.from_pandas(df, preserve_index=False)
    pyarrow_schema = table.schema().as_arrow()
    
    cast_arrays = []
    cast_fields = []
    for field in pyarrow_schema:
        if field.name in arrow_table.schema.names:
            col = arrow_table.column(field.name)
            cast_arrays.append(col.cast(field.type))
            cast_fields.append(field)
            
    arrow_table = pa.table(
        {field.name: arr for field, arr in zip(cast_fields, cast_arrays)},
        schema=pa.schema(cast_fields)
    )
    
    table.overwrite(arrow_table)
    print(f"Successfully ingested {df.shape[0]} rows and {df.shape[1]} columns into Apache Iceberg table: default.climate_esg_analytics")

if __name__ == "__main__":
    generate_and_ingest()
