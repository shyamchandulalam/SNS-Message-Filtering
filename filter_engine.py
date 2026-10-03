import json

def parse_num(val):
    try:
        if isinstance(val, (int, float)):
            return float(val)
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None

def generate_sns_filter_policy(filter_rows):
    """
    Convert list of filter rows (attribute_name, operator, attribute_value)
    into an AWS SNS FilterPolicy dictionary.
    """
    policy = {}
    for f in filter_rows:
        if not f.get("enabled", 1):
            continue
        attr = f["attribute_name"].strip()
        op = f["operator"].strip()
        val_raw = str(f["attribute_value"]).strip()

        num_val = parse_num(val_raw)

        if op in [">", "<", ">=", "<="]:
            if num_val is not None:
                policy[attr] = [{"numeric": [op, num_val]}]
            else:
                policy[attr] = [val_raw]
        elif op in ["=", "equals", "Equals"]:
            if num_val is not None and attr == "price_usd":
                policy[attr] = [{"numeric": ["=", num_val]}]
            else:
                # Can be comma separated list e.g. "electronics, computers"
                items = [x.strip() for x in val_raw.split(",") if x.strip()]
                policy[attr] = items if items else [val_raw]
        elif op in ["!=", "not_equals", "Not Equals"]:
            items = [x.strip() for x in val_raw.split(",") if x.strip()]
            policy[attr] = [{"anything-but": items}]
        elif op in ["in", "In"]:
            items = [x.strip() for x in val_raw.split(",") if x.strip()]
            policy[attr] = items
        elif op in ["contains", "Contains"]:
            policy[attr] = [{"prefix": val_raw}]
        else:
            policy[attr] = [val_raw]

    return policy

def evaluate_single_condition(attr_name, op, expected_val_str, actual_val):
    """
    Evaluates one filter condition against actual attribute value.
    Returns (matched: bool, explanation: str).
    """
    if actual_val is None:
        return False, f"{attr_name} is missing from message"

    op_norm = op.strip().lower()
    val_raw = str(expected_val_str).strip()

    num_actual = parse_num(actual_val)
    num_expected = parse_num(val_raw)

    if op_norm in [">", "greater than"]:
        if num_actual is not None and num_expected is not None:
            ok = num_actual > num_expected
            return ok, f"{attr_name} ({num_actual}) > {num_expected} {'✓' if ok else '✕'}"
        return False, f"{attr_name} not numeric"

    elif op_norm in ["<", "less than"]:
        if num_actual is not None and num_expected is not None:
            ok = num_actual < num_expected
            return ok, f"{attr_name} ({num_actual}) < {num_expected} {'✓' if ok else '✕'}"
        return False, f"{attr_name} not numeric"

    elif op_norm in [">=", "greater than or equal"]:
        if num_actual is not None and num_expected is not None:
            ok = num_actual >= num_expected
            return ok, f"{attr_name} ({num_actual}) >= {num_expected} {'✓' if ok else '✕'}"
        return False, f"{attr_name} not numeric"

    elif op_norm in ["<=", "less than or equal"]:
        if num_actual is not None and num_expected is not None:
            ok = num_actual <= num_expected
            return ok, f"{attr_name} ({num_actual}) <= {num_expected} {'✓' if ok else '✕'}"
        return False, f"{attr_name} not numeric"

    elif op_norm in ["!=", "not equals"]:
        items = [x.strip().lower() for x in val_raw.split(",") if x.strip()]
        str_actual = str(actual_val).strip().lower()
        ok = str_actual not in items
        return ok, f"{attr_name} ({actual_val}) != {val_raw} {'✓' if ok else '✕'}"

    elif op_norm in ["in"]:
        items = [x.strip().lower() for x in val_raw.split(",") if x.strip()]
        str_actual = str(actual_val).strip().lower()
        ok = str_actual in items
        return ok, f"{attr_name} ({actual_val}) in [{val_raw}] {'✓' if ok else '✕'}"

    elif op_norm in ["contains"]:
        str_actual = str(actual_val).strip().lower()
        ok = val_raw.lower() in str_actual
        return ok, f"{attr_name} ({actual_val}) contains '{val_raw}' {'✓' if ok else '✕'}"

    else: # Default '=' or 'equals'
        if num_actual is not None and num_expected is not None and attr_name == "price_usd":
            ok = num_actual == num_expected
            return ok, f"{attr_name} ({num_actual}) = {num_expected} {'✓' if ok else '✕'}"
        else:
            items = [x.strip().lower() for x in val_raw.split(",") if x.strip()]
            str_actual = str(actual_val).strip().lower()
            ok = str_actual in items
            return ok, f"{attr_name} ({actual_val}) = {val_raw} {'✓' if ok else '✕'}"

def evaluate_user_filters(filter_rows, message_attributes):
    """
    Evaluates all enabled filter rows for a user against message attributes.
    Returns:
    {
        "matched": bool,
        "reason": str,
        "details": list
    }
    """
    enabled_filters = [f for f in filter_rows if f.get("enabled", 1)]

    # If no filters assigned, this subscriber receives ALL orders (like all-orders-queue)
    if not enabled_filters:
        return {
            "matched": True,
            "reason": "No filter policy — receives all messages",
            "details": [{
                "attribute": "*",
                "operator": "none",
                "expected": "*",
                "actual": "*",
                "matched": True,
                "explanation": "No filter configured (Wildcard match)"
            }]
        }

    all_matched = True
    details = []
    explanations = []

    for f in enabled_filters:
        attr = f["attribute_name"]
        op = f["operator"]
        val = f["attribute_value"]
        actual = message_attributes.get(attr)

        matched, explanation = evaluate_single_condition(attr, op, val, actual)
        if not matched:
            all_matched = False

        details.append({
            "attribute": attr,
            "operator": op,
            "expected": val,
            "actual": actual,
            "matched": matched,
            "explanation": explanation
        })
        explanations.append(explanation)

    summary_reason = ", ".join(explanations)
    return {
        "matched": all_matched,
        "reason": summary_reason,
        "details": details
    }
