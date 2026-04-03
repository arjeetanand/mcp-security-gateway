package mcp.authz

default decision := {"allow": false, "reason": "policy_denied"}

has_required_role if {
  count(object.get(input, "required_roles", [])) == 0
}

has_required_role if {
  some role in object.get(input.user, "roles", [])
  some required in object.get(input, "required_roles", [])
  role == required
}

decision := {"allow": false, "reason": "missing_required_role"} if {
  not has_required_role
}

decision := {"allow": false, "reason": "approval_required"} if {
  has_required_role
  object.get(input, "requires_approval", false)
  not object.get(input, "is_approved", false)
}

decision := {"allow": true, "reason": "allowed"} if {
  has_required_role
  not object.get(input, "requires_approval", false)
}

decision := {"allow": true, "reason": "allowed_after_approval"} if {
  has_required_role
  object.get(input, "requires_approval", false)
  object.get(input, "is_approved", false)
}
