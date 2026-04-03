package mcp.authz

default decision := {"allow": false, "reason": "policy_denied"}

# Checks if the user has any of the roles required by the tool's policy.
has_required_role if {
  count(object.get(input, "required_roles", [])) == 0
}

has_required_role if {
  some role in object.get(input.user, "roles", [])
  some required in object.get(input, "required_roles", [])
  role == required
}

# Deny access if the user lacks the required security roles.
decision := {"allow": false, "reason": "missing_required_role"} if {
  not has_required_role
}

# Require administrative approval for sensitive tool invocations.
decision := {"allow": false, "reason": "approval_required"} if {
  has_required_role
  object.get(input, "requires_approval", false)
  not object.get(input, "is_approved", false)
}

# Grants access for non-sensitive tools when role requirements are met.
decision := {"allow": true, "reason": "allowed"} if {
  has_required_role
  not object.get(input, "requires_approval", false)
}

decision := {"allow": true, "reason": "allowed_after_approval"} if {
  has_required_role
  object.get(input, "requires_approval", false)
  object.get(input, "is_approved", false)
}
