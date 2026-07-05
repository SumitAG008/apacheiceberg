import re
from typing import Dict, Any, List, Tuple
import pandas as pd

class MeldraValidator:
    @staticmethod
    def validate_dataframe(df: pd.DataFrame, rules: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Validates a Pandas DataFrame against data quality rules (contracts).
        Returns (is_valid, list_of_error_logs)
        """
        is_valid = True
        logs = []

        for idx, rule in enumerate(rules):
            col = rule.get("column")
            op = rule.get("rule")
            val = rule.get("value")

            if col not in df.columns:
                logs.append(f"[contracts] Warning: Column '{col}' referenced in rule #{idx} not present in input data.")
                continue

            if op == "not_null":
                null_count = df[col].isnull().sum()
                if null_count > 0:
                    is_valid = False
                    logs.append(f"[contracts] Violation: Column '{col}' contains {null_count} null value(s) (not_null contract breached).")
                else:
                    logs.append(f"[contracts] Verified: Column '{col}' is fully compliant with not_null contract.")

            elif op == "min":
                try:
                    limit = float(val)
                    violations = df[df[col] < limit]
                    if not violations.empty:
                        is_valid = False
                        logs.append(f"[contracts] Violation: Column '{col}' has values below minimum limit of {limit} (e.g. {violations[col].iloc[0]}).")
                    else:
                        logs.append(f"[contracts] Verified: Column '{col}' values are all >= {limit}.")
                except ValueError:
                    logs.append(f"[contracts] Config Error: Invalid value '{val}' for min limit on column '{col}'.")

            elif op == "max":
                try:
                    limit = float(val)
                    violations = df[df[col] > limit]
                    if not violations.empty:
                        is_valid = False
                        logs.append(f"[contracts] Violation: Column '{col}' has values exceeding maximum limit of {limit} (e.g. {violations[col].iloc[0]}).")
                    else:
                        logs.append(f"[contracts] Verified: Column '{col}' values are all <= {limit}.")
                except ValueError:
                    logs.append(f"[contracts] Config Error: Invalid value '{val}' for max limit on column '{col}'.")

            elif op == "regex":
                try:
                    pattern = re.compile(str(val))
                    # Check strings
                    invalid_mask = df[col].astype(str).apply(lambda x: not bool(pattern.match(x)))
                    violations = df[invalid_mask]
                    if not violations.empty:
                        is_valid = False
                        logs.append(f"[contracts] Violation: Column '{col}' contains values not matching regex pattern '{val}' (e.g. '{violations[col].iloc[0]}').")
                    else:
                        logs.append(f"[contracts] Verified: Column '{col}' conforms to regex pattern '{val}'.")
                except Exception as e:
                    logs.append(f"[contracts] Config Error: Invalid regex pattern '{val}' for column '{col}': {e}")

        return is_valid, logs
