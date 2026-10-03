# SNS FilterHub — Amazon SNS Message Filtering

A dashboard demonstrating **selective message delivery** using Amazon SNS filter policies. Messages route only to subscribers whose filter policies match.

## Problem Statement

Traditional pub/sub delivers every message to every subscriber. SNS filter policies solve this by evaluating message attributes against per-subscription rules, so only relevant messages are delivered.

## Architecture
