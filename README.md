# Stockroom – Inventory Management (FastAPI + MySQL)

## Quick Start
1. Configure `.env` in the project root (see `.env.example`):
   ```ini
   DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/inventory_db
   JWT_SECRET=your-random-secret-key
   ```
2. Activate your virtual environment and install dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
3. Start the application:
   ```bash
   uvicorn main:app --reload
   ```
   > **Note:** The backend automatically reads `.env`, verifies or creates the MySQL database `inventory_db` if it doesn't exist, initializes all tables, and seeds initial data and login accounts. Alternatively, you can pre-load the database using: `mysql -u root -p < database/schema.sql`.

4. Open the app in your browser:
   - Dashboard: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Database Health Check: http://localhost:8000/api/health

## REST Endpoints
- **Health**: `GET /api/health`
- **Auth**: `POST /api/auth/login`, `POST /api/auth/change-password`
- **Dashboard**: `GET /api/dashboard`
- **Products**: `GET/POST /api/products`, `PUT/DELETE /api/products/{id}`, `POST /api/products/{id}/image`
- **Categories & Suppliers**: `GET /api/categories`, `GET/POST /api/suppliers`
- **Stock Movements**: `GET/POST /api/movements`
- **Sales Orders**: `GET/POST /api/sales-orders`, `POST /api/sales-orders/{id}/cancel`
- **Purchase Orders**: `GET/POST /api/purchase-orders`, `POST /api/purchase-orders/{id}/receive`
- **Customers & Users**: `GET/POST /api/customers`, `GET/POST /api/users`, `POST /api/users/{id}/toggle`, `GET /api/audit`

## Login (Separate Admin and User Accounts)
- **Admin**: `admin@stockroom.com` / `Admin@123`
- **Staff User**: `user@stockroom.com` / `User@123`
- Created automatically on first start. Change these passwords and set `JWT_SECRET` in `.env` for production use.
- **Admin**: add/edit/delete products, set exact stock count, cancel sales, create purchase orders, manage users, view audit logs.
- **Staff User**: view catalog, record stock in/out, create sales orders, receive purchase orders.
