# SARDO360 - Property Insight

SARDO360 is a premium real estate property insight platform. It provides a highly optimized, glassy dashboard to view, filter, and export real estate listings fetched from various sources. 

The platform features an invite-only authentication system, dynamic frontend/backend pagination, and high-fidelity PDF and Excel export functionalities.

## Features

- **Secure Authentication**: Invite-only access via CLI user creation. Secure session management using `Flask-Login`.
- **High-Performance Pagination**: Efficient data fetching using SQL `LIMIT` and `OFFSET` queries.
- **Glassmorphism UI**: A stunning, premium aesthetic featuring dynamic mesh background gradients and translucent frosted glass panels.
- **Rich Filtering**: Filter properties by price, location, type, bedrooms, and bathrooms.
- **Reporting**: Generate premium PDF property reports and Excel exports.
- **Dynamic Views**: Toggle between a dense data table and a visual grid of property cards.

## Prerequisites

- **Python 3.10+**
- **PostgreSQL**: Used as the primary database.
- **AWS S3**: Used for storing property images.

## Setup Instructions

### 1. Clone & Environment

Clone the repository and set up a virtual environment:

```bash
cd SARDO360
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configuration

Copy the example environment file and fill in your details:

```bash
cp .env.example .env
```

Ensure you configure the PostgreSQL credentials, AWS keys, and define a strong `SECRET_KEY` for Flask sessions.

### 4. Database Initialization

Ensure PostgreSQL is running, then run the database setup script to initialize the schema:

```bash
python setup_database.py
```

### 5. Create an Administrator Account

Because there is no public signup page, you must create a user via the command line to access the dashboard:

```bash
python create_user.py
```
Follow the interactive prompts to set your username and password.

## Running the Application

Start the Flask development server:

```bash
python app.py
```

Navigate to `http://127.0.0.1:5000` in your browser. You will be redirected to the secure login portal.

## Technologies Used

- **Backend**: Python, Flask, psycopg2, SQLAlchemy (via dependencies).
- **Database**: PostgreSQL.
- **Frontend**: HTML5, Vanilla JavaScript, CSS3 (Custom Glassmorphism Design System).
- **Exports**: ReportLab (PDF), pandas/openpyxl (Excel).
