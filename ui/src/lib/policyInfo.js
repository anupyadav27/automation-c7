// Static metadata for every c7n policy.
// Used client-side to filter rules by service/category and label them.
export const POLICY_INFO = {
  // ── Security Groups (service = ec2, resourceType = Security Group) ──
  'sg-open-ssh':            { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'SSH open to 0.0.0.0/0' },
  'sg-open-rdp':            { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'RDP open to 0.0.0.0/0' },
  'sg-all-ports-open':      { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'All ports open to internet' },
  'sg-open-database-ports': { service:'ec2', resourceType:'Security Group', category:'security', severity:'CRITICAL', label:'Database ports exposed to internet' },
  'sg-unused':              { service:'ec2', resourceType:'Security Group', category:'cost',     severity:'LOW',      label:'Orphaned security group' },
  // ── EC2 Instances ──
  'ec2-no-iam-role':                  { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'HIGH',    label:'No IAM role attached' },
  'ec2-has-key-pair':                 { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'MEDIUM',  label:'SSH key pair in use' },
  'ec2-imdsv1-enabled':               { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'HIGH',    label:'IMDSv1 allowed (SSRF risk)' },
  'ec2-public-ip-check':              { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'WARNING', label:'Instance has public IP' },
  'ec2-missing-tags':                 { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'MEDIUM',  label:'Missing required tags' },
  'ec2-no-detailed-monitoring':       { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'LOW',     label:'No detailed CloudWatch monitoring' },
  'ec2-no-backup-tag':                { service:'ec2', resourceType:'EC2 Instance', category:'security', severity:'MEDIUM',  label:'Missing backup tag' },
  'ec2-underutilised-instances':      { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'CPU < 10% for 14 days' },
  'ec2-stopped-30d':                  { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Stopped 30+ days (EBS still billed)' },
  'ec2-stopped-60d-mark-terminate':   { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Stopped 60+ days — marked for termination' },
  'ec2-old-generation-instance-type': { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Old-gen instance type (m3/m4/c3/c4/t2)' },
  'ec2-long-running-no-ri':           { service:'ec2', resourceType:'EC2 Instance', category:'cost',     severity:'COST',    label:'Running 1yr+ with no reservation' },
  // ── S3 Buckets ──
  's3-public-access-check':               { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'CRITICAL', label:'Public access enabled' },
  's3-no-encryption':                     { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'HIGH',     label:'No server-side encryption' },
  's3-no-versioning':                     { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'MEDIUM',   label:'Versioning disabled' },
  's3-no-access-logging':                 { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'MEDIUM',   label:'No access logging' },
  's3-no-mfa-delete':                     { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'MEDIUM',   label:'MFA delete not enabled' },
  's3-no-ssl-enforcement':                { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'HIGH',     label:'HTTP access allowed' },
  's3-overly-permissive-policy':          { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'CRITICAL', label:'Bucket policy allows Principal: *' },
  's3-untagged-buckets':                  { service:'s3', resourceType:'S3 Bucket', category:'security', severity:'LOW',      label:'Missing required tags' },
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
  'ami-unused-detection': { service:'ami', resourceType:'AMI', category:'cost', severity:'COST', label:'Unused AMI (no running instances for 90+ days)' },
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
    { value:'tag',                   label:'Tag bucket',              destructive:false },
    { value:'notify',                label:'Send notification',        destructive:false },
    { value:'set-bucket-encryption', label:'Enable AES-256 encryption', destructive:false },
    { value:'toggle-versioning',     label:'Enable versioning',        destructive:false },
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
}
