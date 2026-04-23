"""
Seed script: populates the local SQLite demo database used by text2sql.
Run from anywhere: python backend/services/text2sql/db/seed_demo_db.py
"""

from pathlib import Path
import sqlite3
import random
from datetime import datetime, timedelta

DB_PATH = Path(__file__).with_name("data.db")

# ── helpers ──────────────────────────────────────────────────────────────────

def rand_date(start: datetime, end: datetime) -> str:
    delta = end - start
    return (start + timedelta(days=random.randint(0, delta.days))).strftime("%Y-%m-%d")

# ── demo data definitions ─────────────────────────────────────────────────────

PRODUCTS = [
    ("P-1001", "Semiconductor Wafer A", "Components", 42.50),
    ("P-1002", "Semiconductor Wafer B", "Components", 38.75),
    ("P-1003", "PCB Assembly X", "Assemblies", 125.00),
    ("P-1004", "PCB Assembly Y", "Assemblies", 98.50),
    ("P-1005", "Power Module Z", "Modules", 310.00),
    ("P-1006", "RF Filter Kit", "Modules", 215.00),
    ("P-1007", "Memory Chip 8GB", "Components", 22.00),
    ("P-1008", "Memory Chip 16GB", "Components", 40.00),
    ("P-1009", "Optical Sensor", "Sensors", 180.00),
    ("P-1010", "Pressure Sensor", "Sensors", 95.00),
]

REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America"]
SALESPERSONS = ["Alice Chen", "Bob Martinez", "Carol Kim", "David Patel", "Emma Liu"]

DEPARTMENTS = ["Engineering", "Manufacturing", "Sales", "Finance", "Operations", "Quality", "R&D"]
LEVELS = ["Junior", "Mid", "Senior", "Lead", "Manager", "Director"]

SUPPLIERS = [
    ("SUP-001", "Apex Materials", "USA", "Components"),
    ("SUP-002", "Pacific Silicon", "Taiwan", "Wafers"),
    ("SUP-003", "EuroBoard GmbH", "Germany", "PCBs"),
    ("SUP-004", "SensorTech Ltd", "Japan", "Sensors"),
    ("SUP-005", "PowerSys Corp", "South Korea", "Power Modules"),
    ("SUP-006", "GlobalChip Inc", "USA", "Chips"),
    ("SUP-007", "NexMem Technology", "China", "Memory"),
]

PROJECTS = [
    ("PRJ-001", "NextGen Processor", "R&D", "In Progress", 5000000),
    ("PRJ-002", "IoT Platform v2", "Engineering", "In Progress", 1200000),
    ("PRJ-003", "Power Efficiency Upgrade", "Manufacturing", "Completed", 800000),
    ("PRJ-004", "Sensor Array Redesign", "R&D", "Planning", 2300000),
    ("PRJ-005", "Memory Optimization", "Engineering", "In Progress", 950000),
    ("PRJ-006", "RF Module Refresh", "R&D", "Completed", 1500000),
]

RECENT_QUERIES = [
    "Show me total sales revenue by product category",
    "Which employees are in the Engineering department?",
    "What is the average salary by department?",
    "List all inventory items with stock below 50 units",
    "Show supplier performance ratings",
]

# ── table creation ─────────────────────────────────────────────────────────────

def create_schema(cursor: sqlite3.Cursor):
    # query history + metadata tables (normally created by app startup)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recent_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS table_metadata (
            table_name TEXT PRIMARY KEY,
            original_filename TEXT,
            file_extension TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def drop_demo_tables(cursor: sqlite3.Cursor):
    demo_tables = [
        "uploaded_sales_data",
        "uploaded_employee_directory",
        "uploaded_inventory_tracker",
        "uploaded_supplier_scorecard",
        "uploaded_project_budget",
    ]
    for t in demo_tables:
        cursor.execute(f"DROP TABLE IF EXISTS {t}")
        cursor.execute("DELETE FROM table_metadata WHERE table_name = ?", (t,))
    # clear old recent queries so demo queries appear first
    cursor.execute("DELETE FROM recent_queries")


def seed_sales_data(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE uploaded_sales_data (
            Order_ID    TEXT,
            Order_Date  TEXT,
            Product_ID  TEXT,
            Product_Name TEXT,
            Category    TEXT,
            Region      TEXT,
            Salesperson TEXT,
            Units_Sold  INTEGER,
            Unit_Price  REAL,
            Revenue     REAL,
            Cost        REAL,
            Profit      REAL
        )
    """)

    rows = []
    start = datetime(2023, 1, 1)
    end   = datetime(2024, 12, 31)
    for i in range(1, 201):
        prod = random.choice(PRODUCTS)
        units = random.randint(1, 500)
        price = prod[3] * random.uniform(0.9, 1.15)
        cost  = prod[3] * random.uniform(0.55, 0.72)
        rev   = round(units * price, 2)
        cst   = round(units * cost, 2)
        rows.append((
            f"ORD-{i:05d}",
            rand_date(start, end),
            prod[0], prod[1], prod[2],
            random.choice(REGIONS),
            random.choice(SALESPERSONS),
            units,
            round(price, 2),
            rev,
            cst,
            round(rev - cst, 2),
        ))

    cursor.executemany("""
        INSERT INTO uploaded_sales_data VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    cursor.execute("""
        INSERT OR REPLACE INTO table_metadata (table_name, original_filename, file_extension)
        VALUES ('uploaded_sales_data', 'sales_data.csv', '.csv')
    """)
    print(f"  uploaded_sales_data: {len(rows)} rows")


def seed_employee_directory(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE uploaded_employee_directory (
            Employee_ID TEXT,
            First_Name  TEXT,
            Last_Name   TEXT,
            Department  TEXT,
            Level       TEXT,
            Location    TEXT,
            Hire_Date   TEXT,
            Annual_Salary REAL,
            Years_Experience INTEGER,
            Performance_Score REAL
        )
    """)

    first_names = ["James", "Maria", "Wei", "Priya", "Liam", "Sofia", "Yuki", "Omar", "Nina", "Ethan",
                   "Aisha", "Lucas", "Mei", "Daniel", "Elena", "Raj", "Chloe", "Ivan", "Fatima", "Sam"]
    last_names  = ["Smith", "Garcia", "Chen", "Patel", "Johnson", "Kim", "Tanaka", "Hassan", "Novak", "Williams",
                   "Diallo", "Silva", "Wang", "Lee", "Petrov", "Sharma", "Brown", "Okafor", "Mueller", "Taylor"]
    locations   = ["San Jose, CA", "Austin, TX", "Chandler, AZ", "Boston, MA", "Portland, OR"]
    base_salaries = {
        "Junior": 75000, "Mid": 100000, "Senior": 135000,
        "Lead": 160000, "Manager": 180000, "Director": 220000,
    }

    rows = []
    start = datetime(2015, 1, 1)
    end   = datetime(2024, 6, 30)
    for i in range(1, 81):
        dept  = random.choice(DEPARTMENTS)
        level = random.choice(LEVELS)
        base  = base_salaries[level]
        yrs   = random.randint(1, 20)
        rows.append((
            f"EMP-{i:04d}",
            random.choice(first_names),
            random.choice(last_names),
            dept, level,
            random.choice(locations),
            rand_date(start, end),
            round(base * random.uniform(0.85, 1.20), 2),
            yrs,
            round(random.uniform(2.5, 5.0), 1),
        ))

    cursor.executemany("""
        INSERT INTO uploaded_employee_directory VALUES (?,?,?,?,?,?,?,?,?,?)
    """, rows)
    cursor.execute("""
        INSERT OR REPLACE INTO table_metadata (table_name, original_filename, file_extension)
        VALUES ('uploaded_employee_directory', 'employee_directory.xlsx', '.xlsx')
    """)
    print(f"  uploaded_employee_directory: {len(rows)} rows")


def seed_inventory_tracker(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE uploaded_inventory_tracker (
            Item_ID         TEXT,
            Item_Name       TEXT,
            Category        TEXT,
            Warehouse       TEXT,
            Stock_On_Hand   INTEGER,
            Reorder_Point   INTEGER,
            Unit_Cost       REAL,
            Total_Value     REAL,
            Last_Received   TEXT,
            Supplier_ID     TEXT,
            Lead_Time_Days  INTEGER,
            Status          TEXT
        )
    """)

    items = [
        ("INV-001", "Silicon Wafer 200mm", "Wafers"),
        ("INV-002", "Silicon Wafer 300mm", "Wafers"),
        ("INV-003", "Gold Bond Wire 25µm", "Materials"),
        ("INV-004", "Epoxy Resin Type A", "Materials"),
        ("INV-005", "PCB Blank FR4", "PCBs"),
        ("INV-006", "PCB Blank Rogers", "PCBs"),
        ("INV-007", "DRAM Module DDR5", "Memory"),
        ("INV-008", "Flash NAND 256GB", "Memory"),
        ("INV-009", "Capacitor 10µF", "Passives"),
        ("INV-010", "Resistor 100Ω", "Passives"),
        ("INV-011", "Inductor 10µH", "Passives"),
        ("INV-012", "Solder Paste SAC305", "Consumables"),
        ("INV-013", "Cleaning Solvent IPA", "Consumables"),
        ("INV-014", "Optical Fiber SM", "Optical"),
        ("INV-015", "Laser Diode 1310nm", "Optical"),
    ]
    warehouses = ["WH-A", "WH-B", "WH-C"]
    start = datetime(2024, 1, 1)
    end   = datetime(2025, 4, 1)

    rows = []
    for item in items:
        stock   = random.randint(0, 500)
        reorder = random.randint(50, 150)
        cost    = round(random.uniform(1.5, 500.0), 2)
        sup     = random.choice(SUPPLIERS)[0]
        rows.append((
            item[0], item[1], item[2],
            random.choice(warehouses),
            stock, reorder,
            cost,
            round(stock * cost, 2),
            rand_date(start, end),
            sup,
            random.randint(5, 45),
            "Low Stock" if stock < reorder else "OK",
        ))

    cursor.executemany("""
        INSERT INTO uploaded_inventory_tracker VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    cursor.execute("""
        INSERT OR REPLACE INTO table_metadata (table_name, original_filename, file_extension)
        VALUES ('uploaded_inventory_tracker', 'inventory_tracker.csv', '.csv')
    """)
    print(f"  uploaded_inventory_tracker: {len(rows)} rows")


def seed_supplier_scorecard(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE uploaded_supplier_scorecard (
            Supplier_ID         TEXT,
            Supplier_Name       TEXT,
            Country             TEXT,
            Category            TEXT,
            On_Time_Delivery_Pct REAL,
            Quality_Score       REAL,
            Lead_Time_Days      INTEGER,
            Total_Orders        INTEGER,
            Defect_Rate_Pct     REAL,
            Contract_Value_USD  REAL,
            Preferred           TEXT
        )
    """)

    rows = []
    for sup in SUPPLIERS:
        otd     = round(random.uniform(72, 99), 1)
        quality = round(random.uniform(3.0, 5.0), 2)
        defect  = round(random.uniform(0.1, 3.5), 2)
        rows.append((
            sup[0], sup[1], sup[2], sup[3],
            otd, quality,
            random.randint(5, 45),
            random.randint(20, 300),
            defect,
            round(random.uniform(100000, 5000000), 2),
            "Yes" if otd > 90 and quality > 4.0 else "No",
        ))

    cursor.executemany("""
        INSERT INTO uploaded_supplier_scorecard VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    cursor.execute("""
        INSERT OR REPLACE INTO table_metadata (table_name, original_filename, file_extension)
        VALUES ('uploaded_supplier_scorecard', 'supplier_scorecard.xlsx', '.xlsx')
    """)
    print(f"  uploaded_supplier_scorecard: {len(rows)} rows")


def seed_project_budget(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE uploaded_project_budget (
            Project_ID      TEXT,
            Project_Name    TEXT,
            Department      TEXT,
            Status          TEXT,
            Budget_USD      REAL,
            Spent_USD       REAL,
            Remaining_USD   REAL,
            Pct_Used        REAL,
            Start_Date      TEXT,
            End_Date        TEXT,
            Project_Lead    TEXT
        )
    """)

    leads = ["Alice Chen", "Bob Martinez", "Carol Kim", "David Patel", "Emma Liu", "Raj Sharma"]
    start_base = datetime(2023, 6, 1)
    rows = []
    for proj in PROJECTS:
        spent   = round(proj[4] * random.uniform(0.10, 0.95), 2)
        remain  = round(proj[4] - spent, 2)
        pct     = round(spent / proj[4] * 100, 1)
        s_date  = rand_date(start_base, datetime(2024, 3, 1))
        e_date  = rand_date(datetime(2025, 1, 1), datetime(2026, 12, 31))
        rows.append((
            proj[0], proj[1], proj[2], proj[3],
            float(proj[4]), spent, remain, pct,
            s_date, e_date,
            random.choice(leads),
        ))

    cursor.executemany("""
        INSERT INTO uploaded_project_budget VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    cursor.execute("""
        INSERT OR REPLACE INTO table_metadata (table_name, original_filename, file_extension)
        VALUES ('uploaded_project_budget', 'project_budget.csv', '.csv')
    """)
    print(f"  uploaded_project_budget: {len(rows)} rows")


def seed_recent_queries(cursor: sqlite3.Cursor):
    for q in RECENT_QUERIES:
        cursor.execute(
            "INSERT INTO recent_queries (query_text) VALUES (?)", (q,)
        )
    print(f"  recent_queries: {len(RECENT_QUERIES)} entries seeded")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    random.seed(42)
    print(f"Seeding demo database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    create_schema(cursor)
    drop_demo_tables(cursor)
    conn.commit()

    seed_sales_data(conn)
    seed_employee_directory(conn)
    seed_inventory_tracker(conn)
    seed_supplier_scorecard(conn)
    seed_project_budget(conn)
    seed_recent_queries(cursor)

    conn.commit()
    conn.close()
    print("\nDone. Demo database ready.")
    print("\nDemo tables available:")
    print("  • uploaded_sales_data          — 200 sales orders (2023-2024)")
    print("  • uploaded_employee_directory  — 80 employees across departments")
    print("  • uploaded_inventory_tracker   — 15 inventory items with stock levels")
    print("  • uploaded_supplier_scorecard  — 7 suppliers with KPIs")
    print("  • uploaded_project_budget      — 6 R&D/engineering projects")
    print("\nTry asking:")
    print('  "Show me total revenue by product category"')
    print('  "Which employees earn above $150,000?"')
    print('  "List inventory items with low stock"')
    print('  "Which suppliers have on-time delivery above 90%?"')
    print('  "What is the budget utilization for each project?"')


if __name__ == "__main__":
    main()
