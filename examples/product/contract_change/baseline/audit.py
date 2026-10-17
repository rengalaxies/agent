"""Generated bounded consumer: integer minor units only."""
MAPPING = {'amount': ['amount', 1], 'customer_id': ['customer_id', 1]}

def consume(event):
    return {target: event[source] * factor
            for target, (source, factor) in MAPPING.items()}
