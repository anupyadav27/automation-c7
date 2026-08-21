# Resource panel columns

Click a resource in the diagram and a panel opens. This is what it shows,
for every type in the estate, and where each column is read from.

**Generated** — `python3 scripts/build-panel-reference.py > docs/panel-columns.md`.

---

## The four tiers

Three tiers are structural and identical for every resource. One varies.

| Tier | Shows | Columns | Read from | |
|---|---|---|---|---|
| **1** | Identity and placement | name · type · ARN · account · region · AZ · the containers it sits in · tags | `inventory_assets` columns | the envelope every asset carries. Present for all 139 types, no catalog needed |
| **2** | What this resource IS | per type — see the table below | `metadata`, written from `rule_diagram_discovery` | the only tier that varies. An EC2 instance shows its type and state; a bucket shows encryption and versioning |
| **3** | What it is made of | child resources — an instance's ENIs and volumes, a cluster's node groups | `out/edges.csv`, outgoing | composition, read from edges rather than declared. A field holding a list is a child, not a column |
| **4** | What governs it, and what it governs | security groups · IAM roles · KMS keys · log destinations | `out/edges.csv`, both directions | the supporting services, seen from the resource rather than from the border. Incoming edges are phrased from this end: a security group *protects* the interfaces whose edges point at it |

Tiers 3 and 4 are one section in the panel — **Related** — because the
question is one question: what does this touch, and how. It is drawn as
a tree, because the hierarchy IS the answer: a key sits under the volume
it encrypts, an interface under the group that protects it.

```
Related · 5
  ▾ attached-to    vol-0f86d867…      100 GB · gp3
      encrypted-by   ad688fb2-569a…   kms.key
  ▾ attached-to    eni-054ed2af…      in-use
      protected-by   eks-cluster-sg…  ec2.security_group
    assumes        onam-eks-node-…    iam.instance_profile
```

Every branch opens by default and each one collapses. Measured: 280
assets reach depth 1, 19 reach 2, 11 reach 3, one reaches 4; the median
asset has **one** distinct relation. That shallowness is why opening by
default is safe — and why a security group with ten interfaces still
needs the collapse, so it cannot push the rest of the panel off screen.

Three rules the walk follows, each pinned by a test in `related.test.ts`:

- **The tree is assembled on keys, not names.** Two EKS nodes share a
  Name tag, and matching on the displayed name hangs a key under the
  wrong volume.
- **Placement is skipped.** Every resource is `contained-in` its subnet,
  VPC, region and account, and the panel header states all four already.
- **Incoming edges are inverted.** A security group's panel lists what it
  *protects*. Reusing the outbound word would claim the group is
  protected by the thing it protects.
- **A node is visited once.** The graph has 34 bidirectional pairs, and
  without the guard an instance appears beneath its own volume.

An oversized group collapses to a summary row carrying the true total —
356 rule records point at one security group, and showing five of them
without saying so would be a panel that lies. The roll-up happens per
BRANCH: five interfaces under one group and five under another are two
groups of five, not one of ten.

---

Tier 2 is the only tier that needs a catalog, because it is the only one
whose answer differs per resource. `rule_diagram_discovery` holds it, and
it drives two things at once: which fields `emit` stores in
`inventory_assets.metadata`, and which columns the panel shows. One list,
so a field worth storing is a field worth showing.

---

## Where a Tier 2 column comes from

| `source` | Meaning |
|---|---|
| `list` | the field arrived in the collector's own list or describe call — free |
| `enrich:<operation>` | it needed a second, per-resource call |

8 types pay for a second call — 11 calls in all — because
their list call returns an identifier and little else:

| Type | Second call | Why |
|---|---|---|
| `dynamodb.table` | `describe_table` | list_tables returns names only - size, item count, billing mode and encryption all need the describe |
| `ecs.service` | `describe_services` | list_services returns ARNs only |
| `eks.cluster` | `describe_cluster` | list_clusters returns names only — every field worth having needs the describe |
| `eks.nodegroup` | `describe_nodegroup` | the autoScalingGroups this pool created live here, and they are the only collected link from an EKS cluster to the EC2 that runs it |
| `s3.bucket` | `get_bucket_encryption` | list_buckets returns a name and a date. Whether a bucket is encrypted is the first thing anyone asks and it needs its own call |
| `s3.bucket` | `get_bucket_location` | buckets are global in the API and regional in fact; without this every bucket draws in the wrong region |
| `s3.bucket` | `get_bucket_versioning` | versioning decides whether a delete is recoverable, and whether old versions are quietly being billed |
| `s3.bucket` | `get_public_access_block` | the four block settings are the difference between a private bucket and a public one |
| `sns.topic` | `get_topic_attributes` | list_topics returns an ARN and nothing else. The subscription counts — confirmed, pending, deleted — are the only signal that a topic is wired to anything |
| `sqs.queue` | `get_queue_attributes` | list_queues returns a URL. Whether a queue is FIFO, encrypted, or has a dead-letter target is only here |
| `stepfunctions.state_machine` | `describe_state_machine` | the state machine definition names every resource it invokes; without it a workflow has no members |

---

## Every type, and its Tier 2 columns

139 types in the estate; 125 carry Tier 2 columns and
14 do not. The ones that do not are listed after the
table with the reason — every one of them still has Tiers 1, 3 and 4.


### boundary — drawn as a container everything else sits inside

| Type | n | Domain | Columns | From |
|---|---|---|---|---|
| `ec2.vpc` | 1 | boundary.network | `cidr_block` · `dhcp_options_id` · `instance_tenancy` · `is_default` · `state` | list |
| `organizations.organization` | 1 | boundary.org | `feature_set` · `master_account_arn` · `master_account_email` · `master_account_id` | list |
| `ec2.subnet` | 4 | boundary.segment | `assign_ipv6_address_on_creation` · `auto_public_ip` · `availability_zone_id` · `available_ip_address_count` · `cidr_block` · `default_for_az` · `enable_dns64` · `hostname_type` · `ipv6_native` · `map_customer_owned_ip_on_launch` · `state` · `vpc_id` | list |

### resident — drawn as a box in the layered diagram

| Type | n | Domain | Columns | From |
|---|---|---|---|---|
| `athena.data_catalog` | 1 | resident.analytics | `type` | list |
| `redshift.cluster_parameter_group` | 1 | resident.analytics | `parameter_group_family` | list |
| `apprunner.auto_scaling_configuration` | 1 | resident.api | `auto_scaling_configuration_revision` · `created_at` · `has_associated_service` · `is_default` · `status` | list |
| `apprunner.observability_configuration` | 1 | resident.api | `observability_configuration_revision` | list |
| `iot.certificate` | 1 | resident.application | `creation_date` · `status` | list |
| `iot.domain_configuration` | 3 | resident.application | `service_type` | list |
| `ivs.channel` | 1 | resident.application | `authorized` · `insecure_ingest` · `latency_mode` · `type` | list |
| `ivschat.room` | 1 | resident.application | `create_time` · `update_time` | list |
| `mediaconvert.queue` | 1 | resident.application | `created_at` · `last_updated` · `pricing_plan` · `progressing_jobs_count` · `status` · `submitted_jobs_count` · `type` | list |
| `pinpoint-sms-voice-v2.opt_out_list` | 1 | resident.application | `created_timestamp` · `opt_out_list_name` | list |
| `elb.load_balancer` | 1 | resident.balancer | `canonical_hosted_zone_name_id` · `created_time` · `group_name` · `healthy_threshold` · `interval` · `owner_alias` · `scheme` · `target` · `timeout` · `unhealthy_threshold` · `vpc_id` | list |
| `elbv2.listener` | 2 | resident.balancer | `load_balancer_arn` · `port` · `protocol` · `ssl_policy` | list |
| `elbv2.load_balancer` | 1 | resident.balancer | `canonical_hosted_zone_id` · `created_time` · `dns_name` · `ip_address_type` · `lb_type` · `scheme` · `state_code` · `vpc_id` | list |
| `elbv2.target_group` | 2 | resident.balancer | `health_check_enabled` · `health_check_interval_seconds` · `health_check_port` · `health_check_protocol` · `health_check_timeout_seconds` · `healthy_threshold_count` · `ip_address_type` · `port` · `protocol` · `target_type` · `unhealthy_threshold_count` · `vpc_id` | list |
| `ec2.instance` | 3 | resident.compute | `ami_launch_index` · `architecture` · `boot_mode` · `ebs_optimized` · `ena_support` · `hypervisor` · `image_id` · `instance_type` · `launch_time` · `platform` · `private_ip` · `public_ip` · `state` · `subnet_id` · `tenancy` · `vpc_id` | list |
| `eks.nodegroup` | 2 | resident.compute | `ami_type` · `capacity_type` · `cluster_name` · `created_at` · `disk_size` · `instance_types` · `max_size` · `min_size` · `modified_at` · `node_role` · `release_version` · `status` · `version` | enrich |
| `ecs.task_definition` | 1 | resident.containers | `name` | list |
| `elasticache.cache_parameter_group` | 20 | resident.data | `cache_parameter_group_family` · `is_global` | list |
| `memorydb.parameter_group` | 5 | resident.data | `family` | list |
| `rds.certificate` | 3 | resident.data | `certificate_identifier` · `certificate_type` · `customer_override` · `thumbprint` · `valid_from` · `valid_till` | list |
| `rds.db_instance` | 1 | resident.data | `allocated_storage_gb` · `backup_target` · `db_instance_port` · `db_name` · `dbi_resource_id` · `encrypted` · `engine` · `engine_version` · `instance_class` · `kms_key_id` · `license_model` · `multi_az` · `network_type` · `port` · `publicly_accessible` · `state` · `storage_type` | list |
| `rds.db_parameter_group` | 4 | resident.data | `db_parameter_group_family` | list |
| `rds.db_subnet_group` | 2 | resident.data | `subnet_group_status` · `vpc_id` | list |
| `rds.option_group` | 3 | resident.data | `allows_vpc_and_non_vpc_instance_memberships` · `engine_name` · `major_engine_version` | list |
| `rds.rds_snapshot` | 12 | resident.data | `dbi_resource_id` · `encrypted` · `engine` · `engine_version` · `kms_key_id` · `license_model` · `multi_tenant` · `port` · `snapshot_type` · `status` · `storage_type` · `vpc_id` | list |
| `dax.parameter` | 2 | resident.datastore | `allowed_values` · `change_type` · `data_type` · `is_modifiable` · `parameter_type` · `parameter_value` · `source` | list |
| `dynamodb.table` | 7 | resident.datastore | `billing_mode` · `creation_date_time` · `deletion_protection_enabled` · `encryption` · `item_count` · `last_update_to_pay_per_request_date_time` · `number_of_decreases_today` · `read_capacity_units` · `size_gb` · `state` · `table_id` · `write_capacity_units` | enrich |
| `efs.file_system` | 1 | resident.datastore | `creation_time` · `creation_token` · `encrypted` · `life_cycle_state` · `number_of_mount_targets` · `performance_mode` · `replication_overwrite_protection` · `size_in_bytes_value` · `throughput_mode` · `value_in_archive` · `value_in_ia` · `value_in_standard` | list |
| `s3.bucket` | 55 | resident.datastore | `block_public_acls` · `block_public_policy` · `bucket_region` · `creation_date` · `encrypted` · `ignore_public_acls` · `location_constraint` · `restrict_public_buckets` · `size_gb` · `storage_class` · `versioning` | list + enrich |
| `cloudfront.cloud_front_origin_access_identity` | 2 | resident.edge | `comment` · `s3_canonical_user_id` | list |
| `cloudfront.distribution` | 2 | resident.edge | `aliases_quantity` · `cache_behaviors_quantity` · `custom_error_responses_quantity` · `enabled` · `http_version` · `is_ipv6_enabled` · `last_modified_time` · `origin_groups_quantity` · `origins_quantity` · `price_class` · `staging` · `status` | list |
| `cloudfront.streaming_distribution` | 1 | resident.edge | `aliases_quantity` · `domain_name` · `enabled` · `last_modified_time` · `origin_access_identity` · `price_class` · `status` · `trusted_signers_enabled` · `trusted_signers_quantity` | list |
| `route53.hosted_zone` | 3 | resident.edge | `caller_reference` · `comment` · `private_zone` · `resource_record_set_count` | list |
| `apigatewayv2.api` | 2 | resident.ingress | `api_endpoint` · `api_key_selection_expression` · `created_date` · `disable_execute_api_endpoint` · `max_age` · `protocol_type` · `route_selection_expression` | list |
| `events.rule` | 4 | resident.integration | `event_bus_name` · `managed_by` · `schedule_expression` · `state` | list |
| `scheduler.schedule_group` | 1 | resident.integration | `state` | list |
| `sns.topic` | 1 | resident.integration | `subscriptions_confirmed` · `subscriptions_deleted` · `subscriptions_pending` | enrich |
| `sqs.queue` | 1 | resident.integration | `approximate_number_of_messages` · `approximate_number_of_messages_delayed` · `approximate_number_of_messages_not_visible` · `created_timestamp` · `delay_seconds` · `last_modified_timestamp` · `maximum_message_size` · `message_retention_period` · `receive_message_wait_time_seconds` · `sqs_managed_sse_enabled` · `visibility_timeout` | enrich |
| `batch.job_definition` | 1 | resident.serverless | `container_orchestration_type` · `disposable` · `execution_role_arn` · `image` · `job_role_arn` · `purpose` · `revision` · `status` · `type` | list |
| `greengrass.connector_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `greengrass.core_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `greengrass.device_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `greengrass.function_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `greengrass.logger_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `greengrass.resource_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `greengrass.subscription_definition` | 1 | resident.serverless | `creation_timestamp` · `last_updated_timestamp` | list |
| `lambda.function` | 4 | resident.serverless | `apply_on` · `code_size` · `ephemeral_storage_size` · `last_modified` · `log_format` · `log_group` · `memory_mb` · `package_type` · `role` · `runtime` · `timeout_s` · `tracing_config_mode` · `version` | list |
| `lambda.version` | 10 | resident.serverless | `apply_on` · `code_size` · `ephemeral_storage_size` · `function_name` · `last_modified` · `log_group` · `memory_size` · `package_type` · `role` · `timeout` · `tracing_config_mode` · `version` | list |

### part — drawn inside its parent

| Type | n | Domain | Columns | From |
|---|---|---|---|---|
| `apigatewayv2.stage` | 2 | part | `auto_deploy` · `created_date` · `deployment_id` · `detailed_metrics_enabled` · `last_deployment_status_message` · `last_updated_date` | list |
| `ec2.network_interface` | 18 | part | `attached_instance` · `attachment_id` · `attachment_owner` · `attachment_status` · `description` · `device_index` · `interface_type` · `mac_address` · `private_dns_name` · `private_ip` · `requester` · `requester_managed` · `source_dest_check` · `status` · `subnet_id` · `vpc_id` | list |
| `ec2.volume` | 3 | part | `attached` · `attached_instance` · `create_time` · `encrypted` · `iops` · `kms_key_id` · `multi_attach_enabled` · `size_gb` · `snapshot_id` · `state` · `throughput` · `volume_type` | list |

### door — drawn on the north border — traffic crosses here

| Type | n | Domain | Columns | From |
|---|---|---|---|---|
| `ec2.transit_gateway` | 1 | door.lateral | `amazon_side_asn` · `association_default_route_table_id` · `auto_accept_shared_attachments` · `creation_time` · `default_route_table_association` · `default_route_table_propagation` · `dns_support` · `multicast_support` · `propagation_default_route_table_id` · `security_group_referencing_support` · `state` · `vpn_ecmp_support` | list |
| `directconnect.direct_connect_gateway` | 1 | door.onprem | `amazon_side_asn` · `direct_connect_gateway_name` · `direct_connect_gateway_state` · `owner_account` | list |

### rule — drawn as a rail tab — applies to things rather than running

| Type | n | Domain | Columns | From |
|---|---|---|---|---|
| `athena.work_group` | 1 | rule.governance | `creation_time` · `effective_engine_version` · `selected_engine_version` · `state` | list |
| `cloudformation.stack` | 4 | rule.governance | `change_set_id` · `creation_time` · `deletion_time` · `disable_rollback` · `enable_termination_protection` · `last_updated_time` · `stack_drift_status` · `stack_status` · `stack_status_reason` | list |
| `cloudtrail.trail` | 1 | rule.governance | `has_custom_event_selectors` · `has_insight_selectors` · `home_region` · `include_global_service_events` · `is_multi_region_trail` · `is_organization_trail` · `log_file_validation_enabled` · `s3_bucket_name` | list |
| `cloudwatch.alarm` | 1 | rule.governance | `actions_enabled` · `comparison_operator` · `datapoints_to_alarm` · `evaluation_periods` · `metric_name` · `namespace` · `period` · `state_reason` · `state_value` · `statistic` · `threshold` · `treat_missing_data` | list |
| `cloudwatch.dashboard` | 1 | rule.governance | `last_modified` · `size` | list |
| `config.config_rule` | 1 | rule.governance | `config_rule_id` · `config_rule_state` · `input_parameters` · `maximum_execution_frequency` · `source_identifier` | list |
| `config.configuration_recorder` | 1 | rule.governance | `all_supported` · `include_global_resource_types` · `recording_frequency` · `role_arn` | list |
| `config.configuration_recorder_status` | 1 | rule.governance | `last_start_time` · `last_status` · `last_status_change_time` · `last_stop_time` · `recording` | list |
| `config.delivery_channel` | 1 | rule.governance | `delivery_frequency` · `s3_bucket_name` | list |
| `ivs.playback_restriction_policy` | 1 | rule.governance | `enable_strict_origin_enforcement` | list |
| `organizations.root` | 1 | rule.governance | `id` | list |
| `servicecatalog.accepted_portfolio_share` | 1 | rule.governance | `created_time` · `id` · `provider_name` | list |
| `ssm.document` | 1 | rule.governance | `created_date` · `document_format` · `document_type` · `document_version` · `schema_version` | list |
| `ssm.document_version` | 1 | rule.governance | `created_date` · `document_format` · `document_version` · `is_default_version` · `status` | list |
| `ssm.patch_baseline` | 17 | rule.governance | `baseline_name` · `default_baseline` · `operating_system` | list |
| `xray.sampling_rule` | 1 | rule.governance | `created_at` · `fixed_rate` · `host` · `http_method` · `modified_at` · `priority` · `resource_arn` · `rule_arn` · `sampling_rule_version` · `service_name` · `service_type` · `url_path` | list |
| `elasticache.user` | 1 | rule.identity | `access_string` · `arn` · `authentication_type` · `engine` · `minimum_engine_version` · `status` | list |
| `iam.access_key` | 1 | rule.identity | `create_date` · `status` · `user_name` | list |
| `iam.account_authorization_detail` | 5 | rule.identity | `create_date` · `path` · `permissions_boundary_arn` · `permissions_boundary_type` · `user_id` · `user_name` | list |
| `iam.attached_role_policy` | 59 | rule.identity | `policy_name` | list |
| `iam.attached_user_policy` | 1 | rule.identity | `policy_name` | list |
| `iam.group` | 1 | rule.identity | `create_date` · `group_id` · `path` | list |
| `iam.instance_profile` | 20 | rule.identity | `create_date` · `instance_profile_id` · `path` | list |
| `iam.policy` | 44 | rule.identity | `attachment_count` · `create_date` · `default_version_id` · `is_attachable` · `path` · `permissions_boundary_usage_count` · `update_date` | list |
| `iam.role` | 116 | rule.identity | `assume_role_policy_document_version` · `create_date` · `max_session_duration` · `path` · `role_id` | list |
| `iam.virtual_mfa_device` | 1 | rule.identity | `create_date` · `enable_date` · `password_last_used` · `user_arn` · `user_id` | list |
| `memorydb.user` | 1 | rule.identity | `access_string` · `authentication_type` · `minimum_engine_version` · `status` | list |
| `organizations.account` | 5 | rule.identity | `email` · `id` · `joined_method` · `joined_timestamp` · `status` | list |
| `ec2.flow_log` | 1 | rule.network | `creation_time` · `deliver_logs_status` · `file_format` · `flow_log_status` · `hive_compatible_partitions` · `log_destination` · `log_destination_type` · `max_aggregation_interval` · `per_hour_partition` · `resource_id` · `traffic_type` | list |
| `ec2.network_acl` | 1 | rule.network | `is_default` · `vpc_id` | list |
| `ec2.prefix_list` | 16 | rule.network | `address_family` · `prefix_list_arn` · `state` | list |
| `ec2.route_table` | 1 | rule.network | `vpc_id` | list |
| `ec2.security_group` | 31 | rule.network | `vpc_id` | list |
| `ec2.transit_gateway_route_table` | 1 | rule.network | `creation_time` · `default_association_route_table` · `default_propagation_route_table` · `state` · `transit_gateway_id` | list |
| `networkmanager.global_network` | 1 | rule.network | `created_at` · `state` | list |
| `route53resolver.firewall_domain_list` | 4 | rule.network | `managed_owner_name` | list |
| `route53resolver.resolver_config` | 1 | rule.network | `autodefined_reverse` · `id` | list |
| `route53resolver.resolver_rule` | 1 | rule.network | `domain_name` · `id` · `rule_type` · `share_status` · `status` | list |
| `route53resolver.resolver_rule_association` | 1 | rule.network | `resolver_rule_id` · `status` · `vpc_id` | list |
| `ecs.cluster` | 1 | rule.orchestration | `active_services_count` · `pending_tasks_count` · `registered_container_instances_count` · `running_tasks_count` · `status` | list |
| `eks.cluster` | 1 | rule.orchestration | `authentication_mode` · `created_at` · `endpoint` · `endpoint_private_access` · `endpoint_public_access` · `ip_family` · `k8s_version` · `platform_version` · `role_arn` · `service_ipv4_cidr` · `status` · `vpc_id` | enrich |
| `sagemaker.hub` | 1 | rule.orchestration | `creation_time` · `hub_display_name` · `hub_status` · `last_modified_time` | list |
| `stepfunctions.state_machine` | 1 | rule.orchestration | `creation_date` · `include_execution_data` · `level` · `role_arn` · `status` · `tracing_configuration_enabled` · `type` | list + enrich |
| `acm.certificate` | 1 | rule.platform | `created_at` · `exported` · `has_additional_subject_alternative_names` · `in_use` · `issued_at` · `key_algorithm` · `not_after` · `not_before` · `renewal_eligibility` · `status` · `type` | list |
| `codeartifact.domain` | 1 | rule.platform | `created_time` · `encryption_key` · `status` | list |
| `kms.alias` | 21 | rule.platform | `creation_date` · `last_updated_date` · `target_key_id` | list |
| `kms.grant` | 16 | rule.platform | `creation_date` · `issuing_account` · `key_id` · `retiring_principal` | list |
| `kms.key` | 13 | rule.platform | `key_state` | list |
| `secretsmanager.secret` | 77 | rule.platform | `created_date` · `kms_key_id` · `last_accessed_date` · `last_changed_date` | list |
| `autoscaling.auto_scaling_group` | 3 | rule.scaling | `capacity_rebalance` · `created_time` · `default_cooldown` · `desired` · `health_check_grace_period` · `health_check_type` · `launch_template_version` · `max` · `min` · `new_instances_protected_from_scale_in` · `service_linked_role_arn` · `vpc_zone_identifier` | list |
| `ecs.capacity_provider` | 2 | rule.scaling | `status` | list |

### record — not drawn; carried for reference and edges

| Type | n | Domain | Columns | From |
|---|---|---|---|---|
| `appconfig.deployment_strategy` | 4 | record | `deployment_duration_in_minutes` · `final_bake_time_in_minutes` · `growth_factor` · `growth_type` · `replicate_to` | list |
| `appconfig.extension` | 5 | record | `version_number` | list |
| `autoscaling.launch_configuration` | 1 | record | `created_time` · `ebs_optimized` · `iam_instance_profile` · `image_id` · `instance_monitoring_enabled` · `instance_type` · `key_name` | list |
| `ec2.ami` | 1 | record | `architecture` · `boot_mode` · `creation_date` · `ena_support` · `hypervisor` · `image_location` · `image_type` · `imds_support` · `public` · `root_device_name` · `root_device_type` · `state` | list |
| `ec2.ebs_snapshot` | 1 | record | `encrypted` · `progress` · `size_gb` · `start_time` · `state` · `storage_tier` · `volume_id` | list |
| `ec2.key_pair` | 7 | record | `create_time` · `key_fingerprint` · `key_pair_id` · `key_type` | list |
| `ec2.launch_template` | 3 | record | `create_time` · `created_by` · `default_version_number` · `latest_version_number` | list |
| `ec2.network_insights_access_scope` | 1 | record | `created_date` · `updated_date` | list |
| `ec2.security_group_rule` | 228 | record | `cidr_v4` · `cidr_v6` · `egress` · `from_port` · `group` · `group_owner_id` · `peer_group` · `prefix_list` · `protocol` · `to_port` · `user_id` | list |
| `ec2.spot_instance_request` | 1 | record | `create_time` · `image_id` · `instance_id` · `instance_interruption_behavior` · `instance_type` · `launched_availability_zone` · `message` · `spot_price` · `state` · `status_code` · `type` · `update_time` | list |
| `ec2.verified_access_instance` | 1 | record | `creation_time` · `fips_enabled` · `last_updated_time` | list |
| `ec2.vpc_endpoint` | 1 | record | `creation_timestamp` · `dns_record_ip_type` · `ip_address_type` · `private_dns_enabled` · `requester_managed` · `service_name` · `state` · `vpc_endpoint_type` · `vpc_id` | list |
| `ecr.repository` | 16 | record | `created_at` · `encryption_type` · `registry_id` · `repository_uri` · `scan_on_push` | list |
| `logs.log_group` | 9 | record | `creation_time` · `log_group_arn` · `log_group_class` · `metric_filter_count` · `retention_in_days` · `stored_bytes` | list |
| `securityhub.standard` | 13 | record | `company` · `enabled_by_default` · `product` | list |
| `service-quotas.service_quota_request` | 2 | record | `case_id` · `created` · `global_quota` · `last_updated` · `quota_arn` · `quota_code` · `quota_name` · `requester` · `service_code` · `service_name` · `status` · `unit` | list |
| `snowball.compatible_image` | 2 | record | `ami_id` | list |
| `ssm.ssm_managed_instance` | 3 | record | `agent_version` · `computer_name` · `ip_address` · `is_latest_version` · `last_ping_date_time` · `ping_status` · `platform_name` · `platform_type` · `platform_version` · `resource_type` · `source_type` | list |

### Types with no Tier 2 columns

| Type | n | Why |
|---|---|---|
| `apigateway.account` | 1 | already in the envelope (2) |
| `cloudtrail.channel` | 1 | already in the envelope (2) |
| `codedeploy.deployment_config` | 18 | already in the envelope (2) |
| `dax.parameter_group` | 1 | already in the envelope (1) · noise (1) |
| `ec2.dhcp_options` | 1 | a list or nested object — Tier 3 reads it (2) · already in the envelope (1) · noise (1) |
| `ec2.internet_gateway` | 2 | a list or nested object — Tier 3 reads it (2) · already in the envelope (1) · noise (1) |
| `ec2.principal_id_format` | 1 | already in the envelope (1) · a list or nested object — Tier 3 reads it (1) |
| `ec2.traffic_mirror_filter` | 1 | a list or nested object — Tier 3 reads it (4) · already in the envelope (1) |
| `eks.addon` | 3 | already in the envelope (2) |
| `events.event_bus` | 1 | already in the envelope (2) |
| `gamelift.location` | 1 | already in the envelope (1) |
| `iam.iam_oidc_provider` | 2 | already in the envelope (1) |
| `iam.user_policy` | 1 | already in the envelope (2) |
| `rds.db_security_group` | 1 | already in the envelope (3) · a list or nested object — Tier 3 reads it (2) · noise (1) |

---

## How this list is kept true

`scripts/build-detail-fields.py` reads the real payloads in
`out/assets.json` and proposes columns from what is actually there. It
never invents a field: a column that cannot be filled reads as "this
resource has no encryption setting" when the truth is "nobody asked".

It rejects a field for one of these reasons. The counts are measured
across the estate, so a rule that stops firing shows as a zero rather
than as prose nobody rechecked.

| Rejected | n | Because |
|---|---|---|
| already in the envelope | 242 | Tier 1 already shows it. Matched on value, not on name — `TransitGatewayId` and `FileSystemArn` are identity wearing a service prefix |
| a list or nested object — Tier 3 reads it | 239 | a field holding a list is composition. `BlockDeviceMappings` is the volumes, and volumes are children with panels of their own |
| noise | 68 | request bookkeeping — tokens, markers, checksums — and the long-form text that belongs in a payload viewer rather than a column |
| empty across the estate | 14 | a column no resource in this account can fill |
| too long to be a cell | 9 | longer than a cell can hold. SNS calls its 468-character IAM document `Policy`, while `BlockPublicPolicy` is a boolean — length separates them where no name pattern can |
| about the call, not the resource | 5 | the `ResponseMetadata` subtree: HTTP status, host id, retry count. A panel showing `http_status_code: 200` is reporting on itself |
| numeric twin of a named state | 1 | `State.Code` = 16 beside `State.Name` = "running" is one fact in two forms, and nobody reads the number |

Hand-authored rows win. The generator fills coverage; a human decides what
a thing is called and why it earns a column, and re-running never
overwrites that judgement.
