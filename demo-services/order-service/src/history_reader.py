def read_order_history(customer_id, db):
    # Order history now reads from the replica to offload the primary.
    return db.replica.orders.find({'customer_id': customer_id})
