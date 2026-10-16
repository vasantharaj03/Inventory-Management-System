"""Adds sample sales orders (for demos and screenshots) or removes them again.
  py demo_sales.py           add about 50 sample orders spread over the last 30 days
  py demo_sales.py --clear   remove the sample orders
Sample orders do NOT change stock. They are marked created_by = 'demo'.
"""
import random, sys
from datetime import datetime, timedelta
from sqlalchemy import text
from main import engine

if "--clear" in sys.argv:
    with engine.begin() as c:
        n = c.execute(text("DELETE FROM sales_orders WHERE created_by='demo'")).rowcount
    raise SystemExit(f"Removed {n} sample orders.")

with engine.begin() as c:
    prods = c.execute(text("SELECT id,unit_price FROM products WHERE is_active=1")).all()
    if not prods:
        raise SystemExit("No products found. Add products first.")
    n = 0
    for d in range(29, -1, -1):
        for _ in range(random.choice([0, 1, 1, 2, 2, 3]) + (1 if d < 10 else 0)):
            when = datetime.now() - timedelta(days=d, hours=random.randint(0, 11), minutes=random.randint(0, 59))
            items = [(p[0], float(p[1]), random.randint(1, 5)) for p in random.sample(prods, random.randint(1, min(3, len(prods))))]
            oid = c.execute(text("INSERT INTO sales_orders (customer_id,channel,status,total,created_by,created_at) VALUES (NULL,:ch,'confirmed',:t,'demo',:w)"),
                            {"ch": random.choices(["Direct", "Online", "Retail", "Wholesale"], [4, 5, 3, 2])[0], "t": sum(pr * q for _, pr, q in items), "w": when}).lastrowid
            for pid, pr, q in items:
                c.execute(text("INSERT INTO sales_order_items (order_id,product_id,quantity,unit_price) VALUES (:o,:p,:q,:u)"), {"o": oid, "p": pid, "q": q, "u": pr})
            n += 1
print(f"Added {n} sample sales orders. Refresh the dashboard. Remove them later with: py demo_sales.py --clear")