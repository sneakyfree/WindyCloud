resource "aws_db_subnet_group" "main" {
  name       = "windy-cloud"
  subnet_ids = data.aws_subnets.default.ids
  tags       = { Name = "windy-cloud" }
}

resource "aws_db_instance" "main" {
  identifier = "windy-cloud"

  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_max_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "windy_cloud"
  username = "windy_cloud"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period   = 7
  backup_window             = "08:00-09:00" # UTC — off-peak for us-west-2
  maintenance_window        = "Mon:09:30-Mon:10:30"
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "windy-cloud-final-${formatdate("YYYYMMDDhhmmss", timestamp())}"

  # Multi-AZ is off at launch; flip to true after real revenue.
  multi_az = false

  performance_insights_enabled = true
  auto_minor_version_upgrade   = true

  tags = { Name = "windy-cloud" }

  lifecycle {
    # Prevents Terraform from churning the final_snapshot_identifier
    # on every plan just because `timestamp()` moved.
    ignore_changes = [final_snapshot_identifier]
  }
}
