import os
import sqlite3
import csv

def export_all():
    db_path = os.path.join(os.getcwd(), 'db', 'docusphere.db')
    if not os.path.exists(db_path):
        print("Database not found at:", db_path)
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cursor.fetchall() if not r[0].startswith('sqlite_')]

    export_dir = os.path.join(os.getcwd(), 'db_export')
    os.makedirs(export_dir, exist_ok=True)

    for table in tables:
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        headers = [d[0] for d in cursor.description]
        csv_path = os.path.join(export_dir, f"{table}.csv")
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        print(f"Exported '{table}' ({len(rows)} rows) -> {csv_path}")

    conn.close()

if __name__ == '__main__':
    export_all()
