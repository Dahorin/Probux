#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

from app import app
from extensions import db
from models import Product

with app.app_context():
    products = Product.query.all()
    print(f"Found {len(products)} products")

    for product in products:
        old_price = product.price_per_robux
        product.price_per_robux = 0.034
        print(f"Updated '{product.name}': {old_price} -> 0.034")

    db.session.commit()
    print("Database updated successfully!")

    # Verify
    products = Product.query.all()
    print("\nVerification:")
    for p in products:
        print(f"{p.name}: price_per_robux = {p.price_per_robux}")
