import os, time, hmac, hashlib, secrets, jwt
from typing import Optional, Literal
from urllib.parse import quote_plus
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Load environment variables (.env) from project root or backend directory
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path and os.path.exists(_dotenv_path):
    load_dotenv(_dotenv_path)
else:
    for _candidate in [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]:
        if _candidate.exists():
            load_dotenv(_candidate)
            break

def get_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if raw_url:
        if raw_url.startswith("mysql://"):
            return "mysql+pymysql://" + raw_url[len("mysql://"):]
        return raw_url

    # Fallback to discrete environment variables
    user = os.getenv("DB_USER") or os.getenv("MYSQL_USER") or "root"
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or "root"
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or "localhost"
    port = os.getenv("DB_PORT") or os.getenv("MYSQL_PORT") or "3306"
    db_name = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or "inventory_db"

    return f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db_name}"

DB_URL = get_database_url()

def ensure_database_exists(db_url: str):
    """Ensure the target MySQL database exists prior to connecting."""
    try:
        url_obj = make_url(db_url)
        db_name = url_obj.database
        if not db_name:
            return
        server_url = url_obj.set(database="")
        server_engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
        with server_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
        server_engine.dispose()
    except Exception as e:
        print(f"[Database Warning] Could not ensure database exists: {e}")

ensure_database_exists(DB_URL)

engine = create_engine(
    DB_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

app = FastAPI(title="Inventory API", version="1.0")

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None
    unit_price: float = Field(ge=0)
    quantity: int = Field(ge=0, default=0)
    reorder_level: int = Field(ge=0, default=10)
    image: Optional[str] = Field(default=None, max_length=900000)


class MovementIn(BaseModel):
    product_id: int
    type: Literal["IN", "OUT", "ADJUST"]
    quantity: int = Field(ge=0)
    note: Optional[str] = None


def rows(conn, sql, **p):
    return [dict(r) for r in conn.execute(text(sql), p).mappings()]


SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")


def hash_pw(pw):
    salt = secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()


def check_pw(pw, stored):
    salt, h = stored.split("$")
    return hmac.compare_digest(h, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex())


def current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in")
    try:
        return jwt.decode(authorization[7:], SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired. Please sign in again")


def admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


class LoginIn(BaseModel):
    email: str
    password: str
    role: Literal["admin", "user"]


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6)
    role: Literal["admin", "user"] = "user"



@app.post("/api/auth/login")
def login(b: LoginIn):
    with engine.connect() as c:
        u = rows(c, "SELECT * FROM users WHERE email=:e AND is_active=1", e=b.email.strip().lower())
    if not u or not check_pw(b.password, u[0]["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    u = u[0]
    if u["role"] != b.role:
        raise HTTPException(403, f"This is a {u['role']} account. Use the {u['role'].title()} sign-in tab.")
    token = jwt.encode({"sub": str(u["id"]), "name": u["name"], "role": u["role"], "exp": int(time.time()) + 8 * 3600}, SECRET, algorithm="HS256")
    return {"token": token, "user": {"name": u["name"], "email": u["email"], "role": u["role"]}}


@app.get("/api/users", dependencies=[Depends(admin)])
def list_users():
    with engine.connect() as c:
        return rows(c, "SELECT id,name,email,role,is_active,created_at FROM users ORDER BY role, name")


@app.post("/api/users", status_code=201, dependencies=[Depends(admin)])
def create_user(u: UserIn):
    with engine.begin() as c:
        try:
            c.execute(text("INSERT INTO users (name,email,password_hash,role) VALUES (:n,:e,:p,:r)"),
                      {"n": u.name, "e": u.email.strip().lower(), "p": hash_pw(u.password), "r": u.role})
        except Exception:
            raise HTTPException(409, "Email already in use")
    return {"ok": True}


@app.get("/api/dashboard", dependencies=[Depends(current_user)])
def dashboard():
    with engine.connect() as c:
        kpis = rows(c, """SELECT COUNT(*) products, COALESCE(SUM(quantity*unit_price),0) value,
            COALESCE(SUM(quantity>0 AND quantity<=reorder_level),0) low,
            COALESCE(SUM(quantity=0),0) out_of_stock FROM products WHERE is_active=1""")[0]
        return {
            "kpis": kpis,
            "by_category": rows(c, """SELECT COALESCE(c.name,'Uncategorized') name, SUM(p.quantity*p.unit_price) value
                FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.is_active=1
                GROUP BY c.name ORDER BY value DESC"""),
            "trend": rows(c, """SELECT DATE_FORMAT(created_at,'%Y-%m-%d') day, type, SUM(quantity) qty
                FROM stock_movements WHERE type IN ('IN','OUT') AND created_at >= CURDATE() - INTERVAL 29 DAY
                GROUP BY day, type ORDER BY day"""),
            "low_stock": rows(c, """SELECT id, sku, name, quantity, reorder_level, image FROM products
                WHERE is_active=1 AND quantity<=reorder_level ORDER BY quantity/NULLIF(reorder_level,0) LIMIT 6"""),
            "sales": rows(c, """SELECT COALESCE(SUM(m.quantity),0) units, COALESCE(SUM(m.quantity*p.unit_price),0) revenue, COUNT(*) orders
                FROM stock_movements m JOIN products p ON p.id=m.product_id WHERE m.type='OUT' AND m.created_at >= NOW() - INTERVAL 30 DAY""")[0],
            "bands": rows(c, """SELECT COALESCE(SUM(quantity>reorder_level*2),0) high, COALESCE(SUM(quantity>reorder_level AND quantity<=reorder_level*2),0) near,
                COALESCE(SUM(quantity<=reorder_level),0) low, COALESCE(SUM(quantity),0) units FROM products WHERE is_active=1""")[0],
            "top": rows(c, """SELECT p.id, p.name, p.sku, p.quantity, p.reorder_level, p.image, SUM(m.quantity) sold FROM stock_movements m
                JOIN products p ON p.id=m.product_id WHERE m.type='OUT' AND m.created_at >= NOW() - INTERVAL 30 DAY GROUP BY p.id ORDER BY sold DESC LIMIT 4"""),
            "turnover": rows(c, """SELECT COALESCE(c.name,'Uncategorized') name,
                ROUND(100*COALESCE(SUM(o.sold),0)/NULLIF(SUM(p.quantity)+COALESCE(SUM(o.sold),0),0)) pct FROM products p
                LEFT JOIN categories c ON c.id=p.category_id
                LEFT JOIN (SELECT product_id, SUM(quantity) sold FROM stock_movements WHERE type='OUT' AND created_at >= NOW() - INTERVAL 30 DAY GROUP BY product_id) o ON o.product_id=p.id
                WHERE p.is_active=1 GROUP BY c.name"""),
            "channels": rows(c, """SELECT channel, COUNT(*) orders, COALESCE(SUM(total),0) revenue FROM sales_orders
                WHERE status='confirmed' AND created_at >= NOW() - INTERVAL 30 DAY GROUP BY channel ORDER BY revenue DESC"""),
            "recent": rows(c, """SELECT m.id, p.name product, m.type, m.quantity, m.note, m.created_at
                FROM stock_movements m JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT 6"""),
        }


@app.get("/api/products", dependencies=[Depends(current_user)])
def list_products(search: str = "", category_id: Optional[int] = None, low_only: bool = False):
    sql = """SELECT p.*, c.name category, s.name supplier FROM products p
        LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN suppliers s ON s.id=p.supplier_id
        WHERE p.is_active=1 AND (p.name LIKE :q OR p.sku LIKE :q)"""
    params = {"q": f"%{search}%"}
    if category_id:
        sql += " AND p.category_id=:cat"; params["cat"] = category_id
    if low_only:
        sql += " AND p.quantity<=p.reorder_level"
    with engine.connect() as c:
        return rows(c, sql + " ORDER BY p.name", **params)


@app.post("/api/products", status_code=201, dependencies=[Depends(admin)])
def create_product(p: ProductIn):
    with engine.begin() as c:
        try:
            r = c.execute(text("""INSERT INTO products (sku,name,category_id,supplier_id,unit_price,quantity,reorder_level,image)
                VALUES (:sku,:name,:category_id,:supplier_id,:unit_price,:quantity,:reorder_level,:image)"""), p.model_dump())
        except Exception:
            raise HTTPException(409, "SKU already exists")
        if p.quantity:
            c.execute(text("INSERT INTO stock_movements (product_id,type,quantity,note) VALUES (:i,'IN',:q,'Initial stock')"),
                      {"i": r.lastrowid, "q": p.quantity})
        return {"id": r.lastrowid}


@app.put("/api/products/{pid}", dependencies=[Depends(admin)])
def update_product(pid: int, p: ProductIn):
    with engine.begin() as c:
        if not rows(c, "SELECT 1 FROM products WHERE id=:i", i=pid):
            raise HTTPException(404, "Product not found")
        c.execute(text("""UPDATE products SET sku=:sku,name=:name,category_id=:category_id,supplier_id=:supplier_id,
            unit_price=:unit_price,reorder_level=:reorder_level,image=COALESCE(:image,image) WHERE id=:id"""), {**p.model_dump(), "id": pid})
    return {"ok": True}


@app.delete("/api/products/{pid}", dependencies=[Depends(admin)])
def delete_product(pid: int):
    with engine.begin() as c:  # soft delete keeps movement history
        c.execute(text("UPDATE products SET is_active=0 WHERE id=:i"), {"i": pid})
    return {"ok": True}


@app.get("/api/categories", dependencies=[Depends(current_user)])
def categories():
    with engine.connect() as c:
        return rows(c, "SELECT * FROM categories ORDER BY name")


@app.get("/api/suppliers", dependencies=[Depends(current_user)])
def suppliers():
    with engine.connect() as c:
        return rows(c, "SELECT * FROM suppliers ORDER BY name")


@app.get("/api/movements", dependencies=[Depends(current_user)])
def movements(limit: int = 100):
    with engine.connect() as c:
        return rows(c, """SELECT m.id, p.sku, p.name product, m.type, m.quantity, m.note, m.created_at
            FROM stock_movements m JOIN products p ON p.id=m.product_id ORDER BY m.id DESC LIMIT :l""", l=limit)


@app.post("/api/movements", status_code=201)
def add_movement(m: MovementIn, user=Depends(current_user)):
    if m.type == "ADJUST" and user["role"] != "admin":
        raise HTTPException(403, "Only admins can set an exact count")
    with engine.begin() as c:
        cur = rows(c, "SELECT quantity FROM products WHERE id=:i AND is_active=1 FOR UPDATE", i=m.product_id)
        if not cur:
            raise HTTPException(404, "Product not found")
        qty = cur[0]["quantity"]
        new = qty + m.quantity if m.type == "IN" else qty - m.quantity if m.type == "OUT" else m.quantity
        if new < 0:
            raise HTTPException(400, f"Only {qty} units in stock")
        c.execute(text("UPDATE products SET quantity=:q WHERE id=:i"), {"q": new, "i": m.product_id})
        c.execute(text("INSERT INTO stock_movements (product_id,type,quantity,note) VALUES (:i,:t,:q,:n)"),
                  {"i": m.product_id, "t": m.type, "q": m.quantity, "n": m.note})
    return {"quantity": new}


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


# ---------------- Orders, contacts, audit, account ----------------
ALL_TABLES_DDL = [
    """CREATE TABLE IF NOT EXISTS categories (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS suppliers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        email VARCHAR(120),
        phone VARCHAR(30)
    )""",
    """CREATE TABLE IF NOT EXISTS products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        sku VARCHAR(40) NOT NULL UNIQUE,
        name VARCHAR(160) NOT NULL,
        category_id INT,
        supplier_id INT,
        unit_price DECIMAL(12,2) NOT NULL DEFAULT 0,
        quantity INT NOT NULL DEFAULT 0,
        reorder_level INT NOT NULL DEFAULT 10,
        image MEDIUMTEXT NULL,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
        INDEX idx_products_name (name),
        INDEX idx_products_stock (quantity, reorder_level)
    )""",
    """CREATE TABLE IF NOT EXISTS stock_movements (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        product_id INT NOT NULL,
        type ENUM('IN','OUT','ADJUST') NOT NULL,
        quantity INT NOT NULL,
        note VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
        INDEX idx_mov_date (created_at)
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(120) NOT NULL UNIQUE,
        password_hash VARCHAR(200) NOT NULL,
        role ENUM('admin','user') NOT NULL DEFAULT 'user',
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS customers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(120) NOT NULL,
        email VARCHAR(120),
        phone VARCHAR(30),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS sales_orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        customer_id INT NULL,
        channel VARCHAR(30) NOT NULL DEFAULT 'Direct',
        status ENUM('confirmed','cancelled') NOT NULL DEFAULT 'confirmed',
        total DECIMAL(14,2) NOT NULL DEFAULT 0,
        created_by VARCHAR(100),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sales_order_items (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        unit_price DECIMAL(12,2) NOT NULL,
        FOREIGN KEY (order_id) REFERENCES sales_orders(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )""",
    """CREATE TABLE IF NOT EXISTS purchase_orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        supplier_id INT NULL,
        status ENUM('ordered','received') NOT NULL DEFAULT 'ordered',
        total DECIMAL(14,2) NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        received_at TIMESTAMP NULL,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
    )""",
    """CREATE TABLE IF NOT EXISTS purchase_order_items (
        id INT AUTO_INCREMENT PRIMARY KEY,
        po_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        unit_cost DECIMAL(12,2) NOT NULL,
        FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_name VARCHAR(100),
        action VARCHAR(200),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )"""
]


class Line(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class SaleIn(BaseModel):
    customer_id: Optional[int] = None
    channel: Literal["Direct", "Online", "Retail", "Wholesale"] = "Direct"
    items: list[Line] = Field(min_length=1)


class POIn(BaseModel):
    supplier_id: int
    items: list[Line] = Field(min_length=1)


class PwIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None


@app.on_event("startup")
def init_tables():
    try:
        with engine.begin() as c:
            for stmt in ALL_TABLES_DDL:
                c.execute(text(stmt))

            # Ensure products table has image column
            try:
                c.execute(text("ALTER TABLE products ADD COLUMN image MEDIUMTEXT NULL"))
            except Exception:
                pass

            # Seed default users if users table is empty
            if not rows(c, "SELECT 1 FROM users LIMIT 1"):
                for n, e, pw, r in [
                    ("Admin", "admin@stockroom.com", "Admin@123", "admin"),
                    ("Staff User", "user@stockroom.com", "User@123", "user")
                ]:
                    c.execute(
                        text("INSERT INTO users (name,email,password_hash,role) VALUES (:n,:e,:p,:r)"),
                        {"n": n, "e": e, "p": hash_pw(pw), "r": r}
                    )

            # Seed categories if empty
            if not rows(c, "SELECT 1 FROM categories LIMIT 1"):
                for cat in ["Electronics", "Furniture", "Stationery", "Packaging"]:
                    c.execute(text("INSERT INTO categories (name) VALUES (:n)"), {"n": cat})

            # Seed suppliers if empty
            if not rows(c, "SELECT 1 FROM suppliers LIMIT 1"):
                c.execute(text("""INSERT INTO suppliers (name,email,phone) VALUES
                    ('Northwind Traders','sales@northwind.test','+91-9000000001'),
                    ('Apex Supplies','hello@apex.test','+91-9000000002')"""))

            # Seed initial products and movements if products table is empty
            if not rows(c, "SELECT 1 FROM products LIMIT 1"):
                c.execute(text("""INSERT INTO products (sku,name,category_id,supplier_id,unit_price,quantity,reorder_level) VALUES
                    ('EL-1001','Wireless Mouse',1,1,799,120,30),
                    ('EL-1002','Mechanical Keyboard',1,1,3499,18,20),
                    ('EL-1003','27" Monitor',1,2,15999,6,8),
                    ('FU-2001','Ergonomic Chair',2,2,8999,0,5),
                    ('FU-2002','Standing Desk',2,2,19999,14,5),
                    ('ST-3001','A4 Paper Ream',3,1,320,400,100),
                    ('ST-3002','Gel Pens (Box of 12)',3,1,180,45,50),
                    ('PK-4001','Cardboard Box Large',4,2,45,900,200)"""))
                c.execute(text("""INSERT INTO stock_movements (product_id,type,quantity,note,created_at) VALUES
                    (1,'IN',150,'Initial stock',NOW()-INTERVAL 12 DAY),(1,'OUT',30,'Order #1042',NOW()-INTERVAL 9 DAY),
                    (6,'IN',500,'Restock',NOW()-INTERVAL 8 DAY),(6,'OUT',100,'Office supply',NOW()-INTERVAL 5 DAY),
                    (2,'OUT',12,'Order #1055',NOW()-INTERVAL 4 DAY),(3,'OUT',4,'Order #1060',NOW()-INTERVAL 2 DAY),
                    (8,'IN',300,'Restock',NOW()-INTERVAL 1 DAY),(7,'OUT',25,'Order #1071',NOW())"""))

        print("[Database] All tables and seed data initialized successfully.")
    except Exception as ex:
        print(f"[Database Error] Table initialization error: {ex}")


@app.get("/api/health")
def health_check():
    try:
        with engine.connect() as c:
            v = c.execute(text("SELECT VERSION()")).scalar()
            cnt = c.execute(text("SELECT COUNT(*) FROM products WHERE is_active=1")).scalar()
        return {"status": "ok", "database": "connected", "mysql_version": v, "products_count": cnt}
    except Exception as e:
        return {"status": "error", "database": "disconnected", "error": str(e)}


@app.middleware("http")
async def audit(request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if request.method != "GET" and path.startswith("/api/") and resp.status_code < 400 and "/auth/login" not in path:
        try:
            who = jwt.decode(request.headers.get("authorization", "")[7:], SECRET, algorithms=["HS256"])["name"]
            with engine.begin() as c:
                c.execute(text("INSERT INTO audit_log (user_name,action) VALUES (:u,:a)"), {"u": who, "a": f"{request.method} {path}"})
        except Exception:
            pass
    return resp


def move(c, pid, typ, qty, note):
    delta = qty if typ == "IN" else -qty
    c.execute(text("UPDATE products SET quantity=quantity+:d WHERE id=:p"), {"d": delta, "p": pid})
    c.execute(text("INSERT INTO stock_movements (product_id,type,quantity,note) VALUES (:p,:t,:q,:n)"), {"p": pid, "t": typ, "q": qty, "n": note})


@app.get("/api/customers", dependencies=[Depends(current_user)])
def list_customers():
    with engine.connect() as c:
        return rows(c, "SELECT * FROM customers ORDER BY name")


@app.post("/api/customers", status_code=201, dependencies=[Depends(current_user)])
def add_customer(b: PersonIn):
    with engine.begin() as c:
        c.execute(text("INSERT INTO customers (name,email,phone) VALUES (:name,:email,:phone)"), b.model_dump())
    return {"ok": True}


@app.post("/api/suppliers", status_code=201, dependencies=[Depends(admin)])
def add_supplier(b: PersonIn):
    with engine.begin() as c:
        c.execute(text("INSERT INTO suppliers (name,email,phone) VALUES (:name,:email,:phone)"), b.model_dump())
    return {"ok": True}


@app.get("/api/sales-orders", dependencies=[Depends(current_user)])
def list_sales():
    with engine.connect() as c:
        return rows(c, """SELECT o.id,o.channel,o.status,o.total,o.created_by,o.created_at,COALESCE(c.name,'Walk-in') customer,
            (SELECT COALESCE(SUM(quantity),0) FROM sales_order_items WHERE order_id=o.id) units
            FROM sales_orders o LEFT JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC LIMIT 100""")


@app.post("/api/sales-orders", status_code=201)
def create_sale(o: SaleIn, u=Depends(current_user)):
    need = {}
    for it in o.items:
        need[it.product_id] = need.get(it.product_id, 0) + it.quantity
    with engine.begin() as c:
        total, lines = 0.0, []
        for pid, q in need.items():
            r = rows(c, "SELECT id,name,quantity,unit_price FROM products WHERE id=:i AND is_active=1 FOR UPDATE", i=pid)
            if not r:
                raise HTTPException(404, "Product not found")
            if r[0]["quantity"] < q:
                raise HTTPException(400, f"Only {r[0]['quantity']} of {r[0]['name']} in stock")
            total += float(r[0]["unit_price"]) * q
            lines.append((pid, q, r[0]["unit_price"]))
        oid = c.execute(text("INSERT INTO sales_orders (customer_id,channel,total,created_by) VALUES (:c,:ch,:t,:u)"),
                        {"c": o.customer_id, "ch": o.channel, "t": total, "u": u["name"]}).lastrowid
        for pid, q, price in lines:
            c.execute(text("INSERT INTO sales_order_items (order_id,product_id,quantity,unit_price) VALUES (:o,:p,:q,:u)"), {"o": oid, "p": pid, "q": q, "u": price})
            move(c, pid, "OUT", q, f"Sales order #{oid}")
    return {"id": oid, "total": total}


@app.post("/api/sales-orders/{oid}/cancel", dependencies=[Depends(admin)])
def cancel_sale(oid: int):
    with engine.begin() as c:
        o = rows(c, "SELECT status FROM sales_orders WHERE id=:i FOR UPDATE", i=oid)
        if not o or o[0]["status"] != "confirmed":
            raise HTTPException(400, "This order can't be cancelled")
        for it in rows(c, "SELECT product_id,quantity FROM sales_order_items WHERE order_id=:i", i=oid):
            move(c, it["product_id"], "IN", it["quantity"], f"Cancelled sales order #{oid}")
        c.execute(text("UPDATE sales_orders SET status='cancelled' WHERE id=:i"), {"i": oid})
    return {"ok": True}


@app.get("/api/purchase-orders", dependencies=[Depends(current_user)])
def list_pos():
    with engine.connect() as c:
        return rows(c, """SELECT o.id,o.status,o.total,o.created_at,o.received_at,COALESCE(s.name,'Unknown') supplier,
            (SELECT COALESCE(SUM(quantity),0) FROM purchase_order_items WHERE po_id=o.id) units
            FROM purchase_orders o LEFT JOIN suppliers s ON s.id=o.supplier_id ORDER BY o.id DESC LIMIT 100""")


@app.post("/api/purchase-orders", status_code=201, dependencies=[Depends(admin)])
def create_po(o: POIn):
    with engine.begin() as c:
        total, lines = 0.0, []
        for it in o.items:
            r = rows(c, "SELECT unit_price FROM products WHERE id=:i AND is_active=1", i=it.product_id)
            if not r:
                raise HTTPException(404, "Product not found")
            total += float(r[0]["unit_price"]) * it.quantity
            lines.append((it.product_id, it.quantity, r[0]["unit_price"]))
        pid = c.execute(text("INSERT INTO purchase_orders (supplier_id,total) VALUES (:s,:t)"), {"s": o.supplier_id, "t": total}).lastrowid
        for p, q, cost in lines:
            c.execute(text("INSERT INTO purchase_order_items (po_id,product_id,quantity,unit_cost) VALUES (:o,:p,:q,:c)"), {"o": pid, "p": p, "q": q, "c": cost})
    return {"id": pid}


@app.post("/api/purchase-orders/{pid}/receive", dependencies=[Depends(current_user)])
def receive_po(pid: int):
    with engine.begin() as c:
        o = rows(c, "SELECT status FROM purchase_orders WHERE id=:i FOR UPDATE", i=pid)
        if not o or o[0]["status"] != "ordered":
            raise HTTPException(400, "Already received")
        for it in rows(c, "SELECT product_id,quantity FROM purchase_order_items WHERE po_id=:i", i=pid):
            move(c, it["product_id"], "IN", it["quantity"], f"Purchase order #{pid}")
        c.execute(text("UPDATE purchase_orders SET status='received', received_at=NOW() WHERE id=:i"), {"i": pid})
    return {"ok": True}


@app.post("/api/auth/change-password")
def change_pw(b: PwIn, u=Depends(current_user)):
    with engine.begin() as c:
        r = rows(c, "SELECT password_hash FROM users WHERE id=:i", i=int(u["sub"]))
        if not r or not check_pw(b.old_password, r[0]["password_hash"]):
            raise HTTPException(400, "Current password is wrong")
        c.execute(text("UPDATE users SET password_hash=:p WHERE id=:i"), {"p": hash_pw(b.new_password), "i": int(u["sub"])})
    return {"ok": True}


@app.post("/api/users/{uid}/toggle")
def toggle_user(uid: int, u=Depends(admin)):
    if str(uid) == u["sub"]:
        raise HTTPException(400, "You can't disable your own account")
    with engine.begin() as c:
        c.execute(text("UPDATE users SET is_active=1-is_active WHERE id=:i"), {"i": uid})
    return {"ok": True}


@app.get("/api/audit", dependencies=[Depends(admin)])
def audit_log(limit: int = 100):
    with engine.connect() as c:
        return rows(c, "SELECT id,user_name,action,created_at FROM audit_log ORDER BY id DESC LIMIT :l", l=limit)


class ImgIn(BaseModel):
    image: str = Field(default="", max_length=900000)


@app.post("/api/products/{pid}/image", dependencies=[Depends(admin)])
def set_image(pid: int, b: ImgIn):
    with engine.begin() as c:
        c.execute(text("UPDATE products SET image=:i WHERE id=:p"), {"i": b.image or None, "p": pid})
    return {"ok": True}


@app.get("/classic")
def classic():
    return FileResponse(os.path.join(FRONTEND, "classic.html"))