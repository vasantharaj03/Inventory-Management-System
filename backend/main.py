import os, time, hmac, hashlib, secrets, jwt
from typing import Optional, Literal
from datetime import date
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

try:  # read settings from backend/.env if it exists
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

DB_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:password@localhost:3306/inventory_db")
engine = create_engine(DB_URL, pool_pre_ping=True)
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
    start_date: Optional[date] = None
    expiry_date: Optional[date] = None
    set_dates: bool = False


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


@app.on_event("startup")
def seed_users():
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL,
            email VARCHAR(120) NOT NULL UNIQUE, password_hash VARCHAR(200) NOT NULL, role ENUM('admin','user') NOT NULL DEFAULT 'user',
            is_active TINYINT(1) NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""))
        if not rows(c, "SELECT 1 FROM users LIMIT 1"):
            for n, e, pw, r in [("Admin", "admin@stockroom.com", "Admin@123", "admin"), ("Staff User", "user@stockroom.com", "User@123", "user")]:
                c.execute(text("INSERT INTO users (name,email,password_hash,role) VALUES (:n,:e,:p,:r)"), {"n": n, "e": e, "p": hash_pw(pw), "r": r})


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
            COALESCE(SUM(quantity=0),0) out_of_stock,
            COALESCE(SUM(expiry_date IS NOT NULL AND expiry_date < CURDATE()),0) expired,
            COALESCE(SUM(expiry_date IS NOT NULL AND expiry_date >= CURDATE() AND expiry_date <= CURDATE() + INTERVAL 30 DAY),0) expiring FROM products WHERE is_active=1""")[0]
        return {
            "kpis": kpis,
            "by_category": rows(c, """SELECT COALESCE(c.name,'Uncategorized') name, SUM(p.quantity*p.unit_price) value
                FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.is_active=1
                GROUP BY c.name ORDER BY value DESC"""),
            "trend": rows(c, """SELECT DATE_FORMAT(created_at,'%Y-%m-%d') day, type, SUM(quantity) qty
                FROM stock_movements WHERE type IN ('IN','OUT') AND created_at >= CURDATE() - INTERVAL 29 DAY
                GROUP BY day, type ORDER BY day"""),
            "low_stock": rows(c, """SELECT id, sku, name, quantity, reorder_level, image, expiry_date FROM products
                WHERE is_active=1 AND quantity<=reorder_level ORDER BY quantity/NULLIF(reorder_level,0) LIMIT 6"""),
            "sales": rows(c, """SELECT COALESCE(SUM(m.quantity),0) units, COALESCE(SUM(m.quantity*p.unit_price),0) revenue, COUNT(*) orders
                FROM stock_movements m JOIN products p ON p.id=m.product_id WHERE m.type='OUT' AND m.created_at >= NOW() - INTERVAL 30 DAY""")[0],
            "bands": rows(c, """SELECT COALESCE(SUM(quantity>reorder_level*2),0) high, COALESCE(SUM(quantity>reorder_level AND quantity<=reorder_level*2),0) near,
                COALESCE(SUM(quantity<=reorder_level),0) low, COALESCE(SUM(quantity),0) units FROM products WHERE is_active=1""")[0],
            "top": rows(c, """SELECT p.id, p.name, p.sku, p.quantity, p.reorder_level, p.image, p.expiry_date, SUM(m.quantity) sold FROM stock_movements m
                JOIN products p ON p.id=m.product_id WHERE m.type='OUT' AND m.created_at >= NOW() - INTERVAL 30 DAY GROUP BY p.id ORDER BY sold DESC LIMIT 4"""),
            "turnover": rows(c, """SELECT COALESCE(c.name,'Uncategorized') name,
                ROUND(100*COALESCE(SUM(o.sold),0)/NULLIF(SUM(p.quantity)+COALESCE(SUM(o.sold),0),0)) pct FROM products p
                LEFT JOIN categories c ON c.id=p.category_id
                LEFT JOIN (SELECT product_id, SUM(quantity) sold FROM stock_movements WHERE type='OUT' AND created_at >= NOW() - INTERVAL 30 DAY GROUP BY product_id) o ON o.product_id=p.id
                WHERE p.is_active=1 GROUP BY c.name"""),
            "channels": rows(c, """SELECT channel, COUNT(*) orders, COALESCE(SUM(total),0) revenue FROM sales_orders
                WHERE status='confirmed' AND created_at >= NOW() - INTERVAL 30 DAY GROUP BY channel ORDER BY revenue DESC"""),
            "expiry": rows(c, """SELECT id, sku, name, quantity, image, category_id, expiry_date FROM products
                WHERE is_active=1 AND expiry_date IS NOT NULL AND expiry_date <= CURDATE() + INTERVAL 30 DAY ORDER BY expiry_date LIMIT 8"""),
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
    chk_dates(p)
    with engine.begin() as c:
        try:
            r = c.execute(text("""INSERT INTO products (sku,name,category_id,supplier_id,unit_price,quantity,reorder_level,image,start_date,expiry_date)
                VALUES (:sku,:name,:category_id,:supplier_id,:unit_price,:quantity,:reorder_level,:image,:start_date,:expiry_date)"""), p.model_dump())
        except Exception:
            raise HTTPException(409, "SKU already exists")
        if p.quantity:
            c.execute(text("INSERT INTO stock_movements (product_id,type,quantity,note) VALUES (:i,'IN',:q,'Initial stock')"),
                      {"i": r.lastrowid, "q": p.quantity})
        return {"id": r.lastrowid}


@app.put("/api/products/{pid}", dependencies=[Depends(admin)])
def update_product(pid: int, p: ProductIn):
    chk_dates(p)
    with engine.begin() as c:
        if not rows(c, "SELECT 1 FROM products WHERE id=:i", i=pid):
            raise HTTPException(404, "Product not found")
        c.execute(text("""UPDATE products SET sku=:sku,name=:name,category_id=:category_id,supplier_id=:supplier_id,
            unit_price=:unit_price,reorder_level=:reorder_level,image=COALESCE(:image,image),start_date=IF(:set_dates,:start_date,start_date),expiry_date=IF(:set_dates,:expiry_date,expiry_date) WHERE id=:id"""), {**p.model_dump(), "id": pid})
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
DDL_SQL = """CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(120) NOT NULL, email VARCHAR(120), phone VARCHAR(30), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sales_orders (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT NULL, channel VARCHAR(30) NOT NULL DEFAULT 'Direct', status ENUM('confirmed','cancelled') NOT NULL DEFAULT 'confirmed', total DECIMAL(14,2) NOT NULL DEFAULT 0, created_by VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS sales_order_items (id INT AUTO_INCREMENT PRIMARY KEY, order_id INT NOT NULL, product_id INT NOT NULL, quantity INT NOT NULL, unit_price DECIMAL(12,2) NOT NULL, FOREIGN KEY (order_id) REFERENCES sales_orders(id) ON DELETE CASCADE, FOREIGN KEY (product_id) REFERENCES products(id));
CREATE TABLE IF NOT EXISTS purchase_orders (id INT AUTO_INCREMENT PRIMARY KEY, supplier_id INT NULL, status ENUM('ordered','received') NOT NULL DEFAULT 'ordered', total DECIMAL(14,2) NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, received_at TIMESTAMP NULL, FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS purchase_order_items (id INT AUTO_INCREMENT PRIMARY KEY, po_id INT NOT NULL, product_id INT NOT NULL, quantity INT NOT NULL, unit_cost DECIMAL(12,2) NOT NULL, FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE, FOREIGN KEY (product_id) REFERENCES products(id));
CREATE TABLE IF NOT EXISTS audit_log (id BIGINT AUTO_INCREMENT PRIMARY KEY, user_name VARCHAR(100), action VARCHAR(200), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""


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
    with engine.begin() as c:
        for stmt in DDL_SQL.split(";"):
            if stmt.strip():
                c.execute(text(stmt))
    with engine.connect() as c2:
        for col in ("image MEDIUMTEXT NULL", "start_date DATE NULL", "expiry_date DATE NULL"):
            try:
                c2.execute(text(f"ALTER TABLE products ADD COLUMN {col}"))
                c2.commit()
            except Exception:
                c2.rollback()


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
            r = rows(c, "SELECT id,name,quantity,unit_price,expiry_date FROM products WHERE id=:i AND is_active=1 FOR UPDATE", i=pid)
            if not r:
                raise HTTPException(404, "Product not found")
            if r[0]["expiry_date"] and r[0]["expiry_date"] < date.today():
                raise HTTPException(400, f"{r[0]['name']} is expired and can't be sold")
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


def chk_dates(p):
    if p.start_date and p.expiry_date and p.expiry_date < p.start_date:
        raise HTTPException(400, "Expiry date must be after the start date")