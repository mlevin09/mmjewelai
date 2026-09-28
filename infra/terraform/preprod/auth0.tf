resource "auth0_resource_server" "jewelai_api" {
  name                   = "JewelAI ${title(var.deployment_environment)} API"
  identifier             = local.oidc_audience
  signing_alg            = "RS256"
  token_lifetime         = 3600
  token_lifetime_for_web = 3600
  allow_offline_access   = false
}

resource "auth0_client" "jewelai_web" {
  name                = "JewelAI ${title(var.deployment_environment)} Web"
  app_type            = "spa"
  is_first_party      = true
  oidc_conformant     = true
  grant_types         = ["authorization_code"]
  callbacks           = ["${local.web_origin}/auth/callback"]
  allowed_logout_urls = ["${local.web_origin}/login"]
  allowed_origins     = [local.web_origin]
  web_origins         = [local.web_origin]

  jwt_configuration {
    alg = "RS256"
  }
}

resource "auth0_connection" "alpha_users" {
  name     = "jewelai-${var.deployment_environment}-users"
  strategy = "auth0"

  options {
    disable_signup = !var.allow_self_signup
  }
}

resource "auth0_connection_client" "alpha_web" {
  connection_id = auth0_connection.alpha_users.id
  client_id     = auth0_client.jewelai_web.id
}
