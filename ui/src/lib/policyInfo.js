// Static metadata for every c7n policy.
// Used client-side to filter rules by service/category and label them.
export const POLICY_INFO = {
  // ── Security Groups (service = ec2, resourceType = Security Group) ──
  'sg-open-ssh':            { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'SSH open to 0.0.0.0/0',            suggestedActions:['tag','notify','revoke','delete'] },
  'sg-open-rdp':            { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'RDP open to 0.0.0.0/0',            suggestedActions:['tag','notify','revoke','delete'] },
  'sg-all-ports-open':      { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'All ports open to internet',         suggestedActions:['tag','notify','revoke','delete'] },
  'sg-open-database-ports': { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'Database ports exposed to internet',  suggestedActions:['tag','notify','revoke','delete'] },
  // sg-unused: SG is unattached — revoke doesn't fix it, only delete removes the resource
  'sg-unused':              { service:'ec2', resourceType:'Security Group', category:'cost',     severity:'LOW',      label:'Orphaned security group',            suggestedActions:['tag','notify','delete'] },
  // ── EC2 Instances ──
  'ec2-no-iam-role':                  { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'HIGH',    label:'No IAM role attached' },
  'ec2-has-key-pair':                 { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'MEDIUM',  label:'SSH key pair in use' },
  'ec2-imdsv1-enabled':               { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'HIGH',    label:'IMDSv1 allowed (SSRF risk)' },
  'ec2-public-ip-check':              { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'WARNING', label:'Instance has public IP' },
  'ec2-missing-tags':                 { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'MEDIUM',  label:'Missing required tags' },
  'ec2-no-detailed-monitoring':       { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'LOW',     label:'No detailed CloudWatch monitoring' },
  'ec2-no-backup-tag':                { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'MEDIUM',  label:'Missing backup tag' },
  'ec2-underutilised-instances':      { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'CPU < 10% for 14 days' },
  // already stopped — showing 'stop' again does nothing
  'ec2-stopped-30d':                  { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Stopped 30+ days (EBS still billed)',         suggestedActions:['tag','notify','mark-for-op','terminate'] },
  'ec2-stopped-60d-mark-terminate':   { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Stopped 60+ days — marked for termination',   suggestedActions:['tag','notify','mark-for-op','terminate'] },
  'ec2-old-generation-instance-type': { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Old-gen instance type (m3/m4/c3/c4/t2)' },
  'ec2-long-running-no-ri':           { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Running 1yr+ with no reservation' },
  // ── S3 Buckets ──
  // each S3 security policy has one specific automated fix — showing all 7 S3 actions
  // would let users click e.g. "block-public-access" to "fix" an encryption finding (wrong)
  's3-public-access-check':               { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'CRITICAL', label:'Public access enabled',                   suggestedActions:['tag','notify','block-public-access'] },
  's3-no-encryption':                     { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'HIGH',     label:'No server-side encryption',               suggestedActions:['tag','notify','set-bucket-encryption'] },
  's3-no-versioning':                     { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'MEDIUM',   label:'Versioning disabled',                     suggestedActions:['tag','notify','toggle-versioning'] },
  's3-no-access-logging':                 { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'MEDIUM',   label:'No access logging',                       suggestedActions:['tag','notify','enable-access-logging'] },
  's3-no-mfa-delete':                     { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'MEDIUM',   label:'MFA delete not enabled',                  suggestedActions:['tag','notify'] },
  's3-no-ssl-enforcement':                { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'HIGH',     label:'HTTP access allowed',                     suggestedActions:['tag','notify','enforce-ssl-policy'] },
  's3-overly-permissive-policy':          { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'CRITICAL', label:'Bucket policy allows Principal: *',       suggestedActions:['tag','notify'] },
  's3-untagged-buckets':                  { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'LOW',      label:'Missing required tags' },
  's3-empty-buckets':                     { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'LOW',      label:'Empty bucket (0 objects)' },
  's3-replication-no-lifecycle':          { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'COST',     label:'Replicated bucket missing lifecycle rule' },
  's3-incomplete-multipart-uploads':      { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'COST',     label:'Incomplete multipart uploads accumulating' },
  's3-versioned-no-noncurrent-expiration':{ service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'COST',     label:'Non-current versions accumulating' },
  's3-standard-storage-high-cost':        { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'COST',     label:'>100GB Standard storage with low access' },
  's3-transfer-acceleration-unused':      { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'COST',     label:'Transfer acceleration enabled but unused' },
  's3-missing-lifecycle':                 { service:'s3', resourceType:'S3 Bucket', category:'cost',     severity:'COST',     label:'No lifecycle rule for IA/Glacier transition' },
  // ── EBS ──
  'ebs-unattached-volumes':   { service:'ebs', resourceType:'EBS Volume',  category:'cost',     severity:'COST', label:'Unattached volume (incurring cost)' },
  'ebs-unencrypted':          { service:'ebs', resourceType:'EBS Volume',  category:'security', severity:'HIGH', label:'Unencrypted EBS volume' },
  'ebs-gp2-upgrade-to-gp3':  { service:'ebs', resourceType:'EBS Volume',  category:'cost',     severity:'COST', label:'gp2 volume — upgrade to gp3 (20% cheaper)' },
  'ebs-old-snapshots':        { service:'ebs', resourceType:'EBS Snapshot', category:'cost',    severity:'COST', label:'Snapshot older than 90 days' },
  // ── ENI / EIP ──
  'eni-unattached':   { service:'eni', resourceType:'ENI',        category:'cost', severity:'COST', label:'Unattached network interface' },
  'eip-unattached':   { service:'eni', resourceType:'Elastic IP', category:'cost', severity:'COST', label:'Unassociated Elastic IP (~$3.60/month)' },
  // ── AMI ──
  'ami-unused-detection':    { service:'ami', resourceType:'AMI', category:'cost', severity:'COST', label:'Unused AMI (no running instances for 90+ days)' },
  'ami-unused-90d-mark':     { service:'ami', resourceType:'AMI', category:'cost', severity:'COST', label:'Unused AMI 90+ days — marked for deregistration' },
  'ami-unused-deregister':   { service:'ami', resourceType:'AMI', category:'cost', severity:'COST', label:'Unused AMI — deregistered after grace period' },
  'ami-not-in-launch-config':{ service:'ami', resourceType:'AMI', category:'cost', severity:'COST', label:'AMI not in any Launch Template or ASG config' },
  // ── EBS Optimization ──
  'ebs-overprovisioned-iops':        { service:'ebs', resourceType:'EBS Volume',   category:'cost',     severity:'COST',   label:'io1/io2 IOPS < 10% utilised (over-provisioned)' },
  'ebs-untagged':                    { service:'ebs', resourceType:'EBS Volume',   category:'cost',     severity:'MEDIUM', label:'EBS volume missing Name tag' },
  'ebs-orphaned-snapshots':          { service:'ebs', resourceType:'EBS Snapshot', category:'cost',     severity:'COST',   label:'Orphaned snapshot — source volume gone' },
  'ebs-large-low-throughput':        { service:'ebs', resourceType:'EBS Volume',   category:'cost',     severity:'COST',   label:'>500GB volume with very low throughput' },
  'ebs-unattached-30d-cleanup':      { service:'ebs', resourceType:'EBS Volume',   category:'cost',     severity:'COST',   label:'Unattached 30+ days — auto-cleaned up' },
  'ebs-unattached-mark-for-deletion':{ service:'ebs', resourceType:'EBS Volume',   category:'cost',     severity:'COST',   label:'Unattached volume — marked for deletion in 14d' },
  // ── ENI action policies ──
  'eni-unattached-30d-cleanup': { service:'eni', resourceType:'ENI',        category:'cost', severity:'COST', label:'ENI unattached 30+ days — marked for deletion' },
  'eni-marked-delete':          { service:'eni', resourceType:'ENI',        category:'cost', severity:'COST', label:'ENI grace period expired — pending deletion' },
  'eni-untagged':               { service:'eni', resourceType:'ENI',        category:'cost', severity:'LOW',  label:'ENI missing Name tag' },
  'eip-unattached-release':     { service:'eni', resourceType:'Elastic IP', category:'cost', severity:'COST', label:'Elastic IP released after 7 days unattached' },
  // ── S3 Lifecycle (additional) ──
  's3-low-access-suggest-lifecycle':    { service:'s3', resourceType:'S3 Bucket', category:'cost', severity:'COST', label:'< 100 GET requests in 14d — suggest IA/Glacier' },
  's3-large-bucket-low-access':         { service:'s3', resourceType:'S3 Bucket', category:'cost', severity:'COST', label:'>50GB bucket with < 500 GETs in 14d — high cost' },
  's3-zero-access-30d-deep-archive':    { service:'s3', resourceType:'S3 Bucket', category:'cost', severity:'COST', label:'Zero access in 30 days — Deep Archive candidate' },
  's3-ia-missing-glacier-transition':   { service:'s3', resourceType:'S3 Bucket', category:'cost', severity:'COST', label:'Has IA lifecycle but no Glacier transition' },
  's3-enable-request-metrics':          { service:'s3', resourceType:'S3 Bucket', category:'cost', severity:'LOW',  label:'CloudWatch request metrics not enabled' },
  // ── Lambda ──
  'ec2-not-ebs-optimized':     { service:'ec2',    resourceType:'EC2 Instance',   category:'cost',     severity:'COST',     label:'Not EBS-optimized — I/O contention risk' },
  'lambda-not-invoked-30d':    { service:'lambda', resourceType:'Lambda Function', category:'cost',     severity:'COST',     label:'Zero invocations in 30 days — possibly unused' },
  'lambda-missing-tags':       { service:'lambda', resourceType:'Lambda Function', category:'cost',     severity:'MEDIUM',   label:'Missing required tags' },
  'lambda-public-url-no-auth': { service:'lambda', resourceType:'Lambda Function', category:'security', severity:'CRITICAL', label:'Public function URL with no authentication' },
  'lambda-public-invoke-policy':{ service:'lambda', resourceType:'Lambda Function', category:'security', severity:'HIGH',    label:'Resource policy allows cross-account invoke' },
  // ── RDS ──
  'rds-idle-instance':          { service:'rds', resourceType:'RDS Instance', category:'cost',     severity:'COST',   label:'0 connections for 14 days — idle' },
  // already stopped — showing 'stop' again does nothing; AWS auto-restarts in 7d so delete or notify
  'rds-stopped-7d':             { service:'rds', resourceType:'RDS Instance', category:'cost',     severity:'COST',   label:'Stopped instance (auto-restart in 7 days)',   suggestedActions:['tag','notify','delete'] },
  'rds-oversized-instance':     { service:'rds', resourceType:'RDS Instance', category:'cost',     severity:'COST',   label:'Memory-optimised class with low usage' },
  'rds-no-reserved-instance':   { service:'rds', resourceType:'RDS Instance', category:'cost',     severity:'COST',   label:'On-demand 90+ days — no Reserved Instance' },
  'rds-missing-tags':           { service:'rds', resourceType:'RDS Instance', category:'cost',     severity:'MEDIUM', label:'Missing required tags' },
  'rds-snapshot-unencrypted':   { service:'rds', resourceType:'RDS Snapshot', category:'security', severity:'HIGH',   label:'Unencrypted RDS snapshot' },
  'rds-no-auto-minor-upgrade':  { service:'rds', resourceType:'RDS Instance', category:'security', severity:'MEDIUM', label:'Auto minor upgrade disabled — patches blocked' },
  // ── IAM ──
  'iam-user-no-mfa':   { service:'iam', resourceType:'IAM User', category:'security', severity:'CRITICAL', label:'Console user without MFA' },
  'iam-inactive-user': { service:'iam', resourceType:'IAM User', category:'security', severity:'HIGH',     label:'Credentials unused for 90+ days' },
  // ── Security Groups (additional) ──
  'sg-high-rule-count':       { service:'ec2', resourceType:'Security Group', category:'security', severity:'MEDIUM', label:'Many inbound rules open to internet' },
  // AWS does not allow deleting the default SG — that action would always error
  'vpc-default-sg-has-rules': { service:'ec2', resourceType:'Security Group', category:'security', severity:'HIGH',   label:'Default SG has rules — CIS 4.3 violation', suggestedActions:['tag','notify','revoke'] },
  // ── RDS ──
  'rds-public-access':          { service:'rds', resourceType:'RDS Instance', category:'security', severity:'CRITICAL', label:'RDS publicly accessible from internet' },
  'rds-unencrypted':            { service:'rds', resourceType:'RDS Instance', category:'security', severity:'HIGH',     label:'RDS storage not encrypted' },
  'rds-no-multi-az':            { service:'rds', resourceType:'RDS Instance', category:'security', severity:'MEDIUM',   label:'Production RDS running Single-AZ' },
  'rds-no-backup':              { service:'rds', resourceType:'RDS Instance', category:'security', severity:'HIGH',     label:'Backup retention < 7 days' },
  'rds-old-snapshot':           { service:'rds', resourceType:'RDS Snapshot', category:'cost',     severity:'COST',     label:'Manual RDS snapshot older than 90 days' },
  'rds-no-deletion-protection': { service:'rds', resourceType:'RDS Instance', category:'security', severity:'HIGH',     label:'Deletion protection disabled' },
  // ── IAM ──
  'iam-unused-access-key':    { service:'iam', resourceType:'IAM User',   category:'security', severity:'HIGH',     label:'Access key not rotated in 90+ days' },
  'iam-overly-broad-policy':  { service:'iam', resourceType:'IAM Policy', category:'security', severity:'CRITICAL', label:'Policy has wildcard Action or Resource' },
  'iam-unused-role':          { service:'iam', resourceType:'IAM Role',   category:'security', severity:'HIGH',     label:'IAM role unused for 90+ days' },
  'iam-user-inline-policy':   { service:'iam', resourceType:'IAM User',   category:'security', severity:'MEDIUM',   label:'User has direct policy — use groups instead' },
  // ── CloudTrail ──
  'cloudtrail-not-logging':          { service:'cloudtrail', resourceType:'CloudTrail', category:'security', severity:'CRITICAL', label:'Trail logging is DISABLED',           suggestedActions:['tag','notify','enable-trail-logging'] },
  'cloudtrail-no-log-validation':    { service:'cloudtrail', resourceType:'CloudTrail', category:'security', severity:'HIGH',     label:'Log file validation disabled',        suggestedActions:['tag','notify','enable-log-validation'] },
  'cloudtrail-no-kms-encryption':    { service:'cloudtrail', resourceType:'CloudTrail', category:'security', severity:'MEDIUM',   label:'Trail logs not encrypted with KMS' },
  'cloudtrail-no-cloudwatch-logs':   { service:'cloudtrail', resourceType:'CloudTrail', category:'security', severity:'MEDIUM',   label:'Not streaming to CloudWatch Logs' },
  // ── VPC ──
  'vpc-no-flow-logs':            { service:'vpc', resourceType:'VPC',              category:'security', severity:'HIGH',   label:'VPC has no flow logs' },
  'vpc-default-in-use':          { service:'vpc', resourceType:'VPC',              category:'security', severity:'MEDIUM', label:'Default VPC has running instances' },
  'subnet-auto-assign-public-ip':{ service:'vpc', resourceType:'Subnet',           category:'security', severity:'MEDIUM', label:'Subnet auto-assigns public IPs' },
  'igw-attached-non-prod-vpc':   { service:'vpc', resourceType:'Internet Gateway', category:'security', severity:'MEDIUM', label:'IGW attached to non-prod VPC' },
  // ── Secrets Manager ──
  'secret-not-rotated':      { service:'secretsmanager', resourceType:'Secret', category:'security', severity:'HIGH',   label:'Secret not rotated in 90+ days' },
  'secret-rotation-disabled':{ service:'secretsmanager', resourceType:'Secret', category:'security', severity:'MEDIUM', label:'Automatic rotation disabled' },
  'secret-missing-tags':     { service:'secretsmanager', resourceType:'Secret', category:'cost',    severity:'LOW',    label:'Secret missing Owner or Environment tag' },
}

export const SEV_ORDER = { CRITICAL:0, HIGH:1, WARNING:2, MEDIUM:3, COST:4, LOW:5, INFO:6 }

export const SEV_STYLES = {
  CRITICAL: 'bg-red-500/15 text-red-400 border-red-500/30',
  HIGH:     'bg-orange-500/15 text-orange-400 border-orange-500/30',
  WARNING:  'bg-amber-500/15 text-amber-400 border-amber-500/30',
  MEDIUM:   'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  COST:     'bg-violet-500/15 text-violet-400 border-violet-500/30',
  LOW:      'bg-blue-500/15 text-blue-400 border-blue-500/30',
  INFO:     'bg-gray-500/15 text-gray-400 border-gray-500/30',
}

// Actions available per resource type.
// Mark destructive actions with destructive:true — they require a confirmation dialog.
export const RESOURCE_ACTIONS = {
  'Security Group': [
    { value:'tag',    label:'Tag resource',             destructive:false },
    { value:'notify', label:'Send notification',         destructive:false },
    { value:'revoke', label:'Revoke offending rules',    destructive:true  },
    { value:'delete', label:'Delete security group',     destructive:true  },
  ],
  'EC2 Instance': [
    { value:'tag',         label:'Tag resource',                  destructive:false },
    { value:'notify',      label:'Send notification',              destructive:false },
    { value:'stop',        label:'Stop instance',                  destructive:false },
    { value:'mark-for-op', label:'Mark for termination (14 days)', destructive:false },
    { value:'terminate',   label:'Terminate instance',             destructive:true  },
  ],
  'S3 Bucket': [
    { value:'tag',                      label:'Tag bucket',                  destructive:false },
    { value:'notify',                   label:'Send notification',            destructive:false },
    { value:'set-bucket-encryption',    label:'Enable AES-256 encryption',   destructive:false },
    { value:'toggle-versioning',        label:'Enable versioning',            destructive:false },
    { value:'block-public-access',      label:'Block all public access',      destructive:false },
    { value:'enable-access-logging',    label:'Enable access logging',        destructive:false },
    { value:'enforce-ssl-policy',       label:'Enforce SSL-only policy',      destructive:false },
  ],
  'EBS Volume': [
    { value:'tag',      label:'Tag volume',     destructive:false },
    { value:'notify',   label:'Send notification', destructive:false },
    { value:'snapshot', label:'Create snapshot', destructive:false },
    { value:'delete',   label:'Delete volume',   destructive:true  },
  ],
  'EBS Snapshot': [
    { value:'tag',    label:'Tag snapshot',      destructive:false },
    { value:'delete', label:'Delete snapshot',   destructive:true  },
  ],
  'ENI': [
    { value:'tag',    label:'Tag ENI',   destructive:false },
    { value:'delete', label:'Delete ENI', destructive:true  },
  ],
  'Elastic IP': [
    { value:'tag',     label:'Tag EIP',    destructive:false },
    { value:'release', label:'Release EIP', destructive:true  },
  ],
  'AMI': [
    { value:'tag',        label:'Tag AMI',        destructive:false },
    { value:'deregister', label:'Deregister AMI', destructive:true  },
  ],
  'RDS Instance': [
    { value:'tag',    label:'Tag instance',                  destructive:false },
    { value:'notify', label:'Send notification',              destructive:false },
    { value:'stop',   label:'Stop instance',                  destructive:false },
    { value:'delete', label:'Delete instance (with snapshot)', destructive:true  },
  ],
  'RDS Snapshot': [
    { value:'tag',    label:'Tag snapshot',   destructive:false },
    { value:'delete', label:'Delete snapshot', destructive:true  },
  ],
  'IAM User': [
    { value:'tag',                     label:'Tag user',                       destructive:false },
    { value:'notify',                  label:'Send notification',               destructive:false },
    { value:'disable-login-profile',   label:'Disable console login',           destructive:false },
    { value:'deactivate-access-keys',  label:'Deactivate all access keys',      destructive:false },
    { value:'delete',                  label:'Delete IAM user',                 destructive:true  },
  ],
  'IAM Policy': [
    { value:'tag',             label:'Tag policy',                 destructive:false },
    { value:'notify',          label:'Send notification',           destructive:false },
    { value:'detach-policy',   label:'Detach from all principals',  destructive:true  },
    { value:'delete',          label:'Delete policy',               destructive:true  },
  ],
  'IAM Role': [
    { value:'tag',    label:'Tag role',            destructive:false },
    { value:'notify', label:'Send notification',    destructive:false },
    { value:'delete', label:'Delete role',          destructive:true  },
  ],
  'Lambda Function': [
    { value:'tag',    label:'Tag function',   destructive:false },
    { value:'notify', label:'Send notification', destructive:false },
    { value:'delete', label:'Delete function', destructive:true  },
  ],
  'CloudTrail': [
    { value:'tag',                      label:'Tag trail',               destructive:false },
    { value:'notify',                   label:'Send notification',        destructive:false },
    { value:'enable-trail-logging',     label:'Enable logging',           destructive:false },
    { value:'enable-log-validation',    label:'Enable log file validation', destructive:false },
  ],
  'VPC': [
    { value:'tag',    label:'Tag VPC',        destructive:false },
    { value:'notify', label:'Send notification', destructive:false },
  ],
  'Subnet': [
    { value:'tag',    label:'Tag subnet',     destructive:false },
    { value:'notify', label:'Send notification', destructive:false },
  ],
  'Internet Gateway': [
    { value:'tag',    label:'Tag IGW',        destructive:false },
    { value:'notify', label:'Send notification', destructive:false },
  ],
  'Secret': [
    { value:'tag',    label:'Tag secret',     destructive:false },
    { value:'notify', label:'Send notification', destructive:false },
    { value:'delete', label:'Delete secret',   destructive:true  },
  ],
}

// Per-policy descriptions and recommendations shown in Policy Library.
// desc: what the rule checks for; recommendation: what to do when triggered.
export const POLICY_DESC = {
  'sg-open-ssh':            { desc: 'Security groups with unrestricted inbound SSH (port 22) from 0.0.0.0/0 or ::/0.', recommendation: 'Restrict SSH to specific IP ranges or a bastion/VPN CIDR. Never allow 0.0.0.0/0 for SSH.' },
  'sg-open-rdp':            { desc: 'Security groups with unrestricted inbound RDP (port 3389) from any IP.', recommendation: 'Restrict RDP to specific IPs or use a VPN/bastion host. Remove 0.0.0.0/0 rules.' },
  'sg-all-ports-open':      { desc: 'Security groups allowing all inbound traffic (ports 0-65535) from any IP.', recommendation: 'Define explicit rules for required ports only. Delete the catch-all rule.' },
  'sg-open-database-ports': { desc: 'Security groups exposing database ports (MySQL 3306, Postgres 5432, MSSQL 1433, Redis 6379, MongoDB 27017) to the internet.', recommendation: 'Database ports should never be public. Allow only from application security group.' },
  'sg-unused':              { desc: 'Security groups not associated with any EC2, RDS, Lambda, or load balancer resource.', recommendation: 'Verify the SG is truly unused, then delete to reduce attack surface and clutter.' },
  'ec2-no-iam-role':        { desc: 'EC2 instances running without an IAM instance profile/role attached.', recommendation: 'Attach a least-privilege IAM role. Never use long-lived access keys on EC2.' },
  'ec2-has-key-pair':       { desc: 'EC2 instances configured with an SSH key pair, enabling direct SSH access.', recommendation: 'Migrate to SSM Session Manager for shell access. Remove key pairs from production instances.' },
  'ec2-imdsv1-enabled':     { desc: 'EC2 instances with IMDSv1 enabled — vulnerable to SSRF attacks that steal instance credentials.', recommendation: 'Enforce IMDSv2 by setting HttpTokens=required. IMDSv1 was exploited in the Capital One breach.' },
  'ec2-public-ip-check':    { desc: 'EC2 instances with a public IP address directly assigned.', recommendation: 'Use a load balancer or NAT gateway. Public IPs should only be on load balancers, not compute.' },
  'ec2-missing-tags':       { desc: 'EC2 instances missing required governance tags (Owner, Environment, or Project).', recommendation: 'Tag all instances at launch via Service Control Policies or enforce via AWS Config rules.' },
  'ec2-no-backup-tag':      { desc: 'EC2 instances without a Backup tag, indicating no automated backup policy.', recommendation: 'Add a Backup=daily tag and configure AWS Backup to act on it.' },
  'ec2-underutilised-instances':    { desc: 'EC2 instances with CPU utilisation below 10% for 14+ consecutive days.', recommendation: 'Downsize to a smaller instance type or switch to Spot/Savings Plans. Consider termination if unused.' },
  'ec2-stopped-30d':                { desc: 'EC2 instances that have been stopped for 30+ days but still have attached EBS volumes incurring cost.', recommendation: 'Terminate the instance (after snapshotting the EBS) or restart if still needed.' },
  'ec2-stopped-60d-mark-terminate': { desc: 'EC2 instances stopped for 60+ days, marked for termination.', recommendation: 'Review and terminate. Take a final EBS snapshot before deletion.' },
  'ec2-old-generation-instance-type':{ desc: 'EC2 instances using old-generation types (m3, m4, c3, c4, t2) that are more expensive and slower than current gen.', recommendation: 'Migrate to m5/m6i, c5/c6i, or t3/t4g equivalents for better price/performance.' },
  's3-public-access-check':         { desc: 'S3 buckets with public access enabled via ACL or bucket policy, exposing data to the internet.', recommendation: 'Enable Block Public Access settings at the bucket and account level unless serving a public website.' },
  's3-no-encryption':               { desc: 'S3 buckets without server-side encryption (SSE-S3 or SSE-KMS) configured.', recommendation: 'Enable default SSE-S3 encryption on all buckets. Use SSE-KMS for sensitive data requiring audit trails.' },
  's3-no-versioning':               { desc: 'S3 buckets with versioning disabled — data deleted or overwritten cannot be recovered.', recommendation: 'Enable versioning on buckets holding important data. Add lifecycle rules to expire old versions to control cost.' },
  's3-no-access-logging':           { desc: 'S3 buckets without server access logging enabled — no audit trail for object operations.', recommendation: 'Enable access logging to a separate logging bucket for security auditing and incident response.' },
  's3-no-ssl-enforcement':          { desc: 'S3 buckets without a bucket policy enforcing HTTPS-only access.', recommendation: 'Add a bucket policy with aws:SecureTransport: false → Deny to enforce TLS-only access.' },
  's3-overly-permissive-policy':    { desc: 'S3 bucket policies with Principal: * granting access to everyone on the internet.', recommendation: 'Restrict principal to specific AWS accounts, IAM roles, or use aws:PrincipalOrgID condition.' },
  'ebs-unattached-volumes':         { desc: 'EBS volumes not attached to any EC2 instance, still charged at full rate.', recommendation: 'Snapshot the volume for backup then delete it. Unattached volumes cost the same as attached.' },
  'ebs-unencrypted':                { desc: 'EBS volumes without encryption enabled — data at rest is in plaintext.', recommendation: 'Enable EBS encryption by default in the AWS console. For existing volumes, snapshot and restore with encryption.' },
  'ebs-gp2-upgrade-to-gp3':        { desc: 'EBS gp2 volumes that could save 20% cost and gain higher IOPS by upgrading to gp3.', recommendation: 'Modify volume type from gp2 to gp3 (no downtime, same performance baseline, lower cost).' },
  'ebs-old-snapshots':              { desc: 'EBS snapshots older than 90 days with no recent activity.', recommendation: 'Review if the snapshot is still needed. Delete old snapshots to reduce storage cost.' },
  'eni-unattached':                 { desc: 'Elastic Network Interfaces not attached to any instance or resource.', recommendation: 'Delete orphaned ENIs. They accumulate when instances are terminated without proper cleanup.' },
  'eip-unattached':                 { desc: 'Elastic IP addresses not associated with any running instance or network interface, charged at ~$3.60/month.', recommendation: 'Release unused Elastic IPs immediately. AWS charges for unassociated EIPs.' },
  'lambda-public-url-no-auth':      { desc: 'Lambda functions with a public function URL configured without IAM authentication.', recommendation: 'Add IAM auth to the function URL or delete the URL if unused. Unauthenticated URLs are publicly accessible.' },
  'lambda-public-invoke-policy':    { desc: 'Lambda functions with resource policies allowing cross-account or anonymous invocation.', recommendation: 'Restrict resource policy to specific principals. Remove Principal: * entries.' },
  'lambda-not-invoked-30d':         { desc: 'Lambda functions with zero invocations in 30 days — likely unused.', recommendation: 'Review the function purpose. Delete if unused to reduce costs and attack surface.' },
  'rds-public-access':              { desc: 'RDS instances with PubliclyAccessible=true, exposing the database endpoint to the internet.', recommendation: 'Set PubliclyAccessible=false. Database should only be reachable from the application security group.' },
  'rds-unencrypted':                { desc: 'RDS instances with storage encryption disabled — data at rest is in plaintext.', recommendation: 'Enable encryption. For existing unencrypted instances, snapshot and restore to a new encrypted instance.' },
  'rds-no-backup':                  { desc: 'RDS instances with backup retention period set to fewer than 7 days.', recommendation: 'Set backup retention to at least 7 days (30 days recommended for production).' },
  'rds-no-deletion-protection':     { desc: 'RDS instances with deletion protection disabled — can be deleted accidentally.', recommendation: 'Enable deletion protection on all production databases. Require explicit disable before deletion.' },
  'rds-idle-instance':              { desc: 'RDS instances with zero database connections over 14 days — likely idle.', recommendation: 'Stop the instance if temporarily unneeded or delete if permanently unused.' },
  'iam-user-no-mfa':                { desc: 'IAM users with console access but without multi-factor authentication enabled.', recommendation: 'Enforce MFA via IAM policy (aws:MultiFactorAuthPresent: false → Deny). Require MFA for all human users.' },
  'iam-inactive-user':              { desc: 'IAM users with console or API credentials unused for 90+ days.', recommendation: 'Disable or delete the user. Dormant credentials are a common attack vector.' },
  'iam-unused-access-key':          { desc: 'IAM access keys not used or rotated in 90+ days.', recommendation: 'Rotate or delete the key. Set a key rotation policy and use AWS Secrets Manager for automation.' },
  'iam-overly-broad-policy':        { desc: 'IAM policies with wildcard Action (*) or Resource (*) granting excessive permissions.', recommendation: 'Scope down to specific actions and resource ARNs. Use IAM Access Analyzer to generate least-privilege policies.' },
  'iam-unused-role':                { desc: 'IAM roles with no last-used activity in 90+ days.', recommendation: 'Delete unused roles to reduce blast radius. Use IAM Access Analyzer before deletion.' },
  'cloudtrail-not-logging':         { desc: 'CloudTrail trails with logging disabled — no audit log of API calls.', recommendation: 'Re-enable logging immediately. CloudTrail should always be active in every region.' },
  'cloudtrail-no-log-validation':   { desc: 'CloudTrail trails without log file integrity validation — logs could be tampered.', recommendation: 'Enable log file validation. CloudTrail will create SHA-256 digest files to detect tampering.' },
  'vpc-no-flow-logs':               { desc: 'VPCs without VPC Flow Logs enabled — no record of network traffic for forensics.', recommendation: 'Enable Flow Logs for all VPCs, publishing to CloudWatch Logs or S3 for analysis.' },
  'secret-not-rotated':             { desc: 'Secrets Manager secrets not rotated in 90+ days.', recommendation: 'Enable automatic rotation. Use Lambda rotation functions provided by AWS for common databases.' },
  'secret-rotation-disabled':       { desc: 'Secrets Manager secrets with automatic rotation disabled.', recommendation: 'Enable rotation with an appropriate schedule (30–90 days). Use AWS-managed rotation Lambdas.' },
}

// Returns the action list appropriate for a specific set of findings on a resource.
// If any of the policies have suggestedActions, we filter RESOURCE_ACTIONS to that union.
// Falls back to the full resource-type action list when no policy overrides exist.
export function getActionsForFindings(findings, resourceType) {
  const overrideSets = findings
    .map(f => POLICY_INFO[f.policy]?.suggestedActions)
    .filter(Boolean)

  const base = RESOURCE_ACTIONS[resourceType]
    || [{ value:'tag', label:'Tag resource', destructive:false }]

  if (overrideSets.length === 0) return base

  const allowed = new Set(overrideSets.flat())
  return base.filter(a => allowed.has(a.value))
}
