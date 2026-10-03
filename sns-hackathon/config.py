import os

REGION = "us-east-1"

TOPIC_ARN = "arn:aws:sns:us-east-1:541645813476:order-events-topic"

QUEUES = {
    "high_value": {
        "name": "high-value-orders-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/high-value-orders-queue",
    },
    "electronics": {
        "name": "electronics-orders-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/electronics-orders-queue",
    },
    "premium": {
        "name": "premium-customers-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/premium-customers-queue",
    },
    "all": {
        "name": "all-orders-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/all-orders-queue",
    },
}