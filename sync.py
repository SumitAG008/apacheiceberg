import subprocess
import sys

commands = [
    ["git", "init"],
    ["git", "add", "."],
    ["git", "commit", "-m", "Initial commit of Iceberg Data Lake Agent"],
    ["git", "branch", "-M", "main"],
    ["git", "remote", "add", "origin", "https://github.com/SumitAG008/apacheiceberg.git"],
    ["git", "push", "-u", "origin", "main", "--force"]
]

for cmd in commands:
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error executing {' '.join(cmd)}:")
        print(result.stderr)
        # ignore error if remote already exists
        if "remote origin already exists" not in result.stderr:
            sys.exit(1)
    else:
        print(result.stdout)

print("Sync completed successfully.")
