import { useState, useEffect, useMemo } from 'react'
import { runBuild } from '../api'
import { saveToHistory } from '../lib/history'
import { getUserRules, saveUserRule, deleteUserRule, getUserCategories, getUserGroups } from '../lib/userRules'
import { POLICY_DESC, POLICY_INFO } from '../lib/policyInfo'
import ReportTable from '../components/ReportTable'

// Maps c7n resource type names → { service, resourceType } used by ReportTable
const C7N_RESOURCE_META = {
  'ec2':             { service:'ec2',            resourceType:'EC2 Instance' },
  's3':              { service:'s3',             resourceType:'S3 Bucket' },
  'ebs':             { service:'ebs',            resourceType:'EBS Volume' },
  'ebs-snapshot':    { service:'ebs',            resourceType:'EBS Snapshot' },
  'eni':             { service:'eni',            resourceType:'ENI' },
  'elastic-ip':      { service:'eni',            resourceType:'Elastic IP' },
  'ami':             { service:'ami',            resourceType:'AMI' },
  'security-group':  { service:'ec2',            resourceType:'Security Group' },
  'rds':             { service:'rds',            resourceType:'RDS Instance' },
  'rds-snapshot':    { service:'rds',            resourceType:'RDS Snapshot' },
  'iam-user':        { service:'iam',            resourceType:'IAM User' },
  'iam-policy':      { service:'iam',            resourceType:'IAM Policy' },
  'iam-role':        { service:'iam',            resourceType:'IAM Role' },
  'lambda':          { service:'lambda',         resourceType:'Lambda Function' },
  'cloudtrail':      { service:'cloudtrail',     resourceType:'CloudTrail' },
  'vpc':             { service:'vpc',            resourceType:'VPC' },
  'subnet':          { service:'vpc',            resourceType:'Subnet' },
  'internet-gateway':{ service:'vpc',            resourceType:'Internet Gateway' },
  'secrets-manager': { service:'secretsmanager', resourceType:'Secret' },
}

// ── CSV parser (no external deps) ─────────────────────────────────
function parseCSV(text) {
  const lines = text.split('\n')
  const headers = splitCSVLine(lines[0])
  const rows = []
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue
    const cols = splitCSVLine(lines[i])
    if (cols.length < headers.length) continue
    const obj = {}
    headers.forEach((h, idx) => { obj[h] = cols[idx] || '' })
    rows.push(obj)
  }
  return rows
}

function splitCSVLine(line) {
  const cols = []
  let cur = ''
  let inQuote = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (c === '"') {
      if (inQuote && line[i + 1] === '"') { cur += '"'; i++ }
      else inQuote = !inQuote
    } else if (c === ',' && !inQuote) {
      cols.push(cur); cur = ''
    } else {
      cur += c
    }
  }
  cols.push(cur)
  return cols
}

// ── Common op values ────────────────────────────────────────────────
const OPS = ['eq','ne','gt','gte','lt','lte','in','not-in','contains','glob','regex']

// ── Known values for schema fields that are typed 'string' but have fixed choices
const KNOWN_VALUES = {
  crypto:            ['AES256', 'aws:kms'],
  'sse-algorithm':   ['AES256', 'aws:kms'],
  statistics:        ['Average', 'Sum', 'Maximum', 'Minimum', 'SampleCount'],
  state:             ['present', 'absent', 'enabled', 'disabled'],
  operator:          ['and', 'or'],
  kind:              ['lambda', 'sns', 'sqs'],
}

// ── Per-resource attribute keys + enum values
const RESOURCE_ATTRS = {
  'access-analyzer-finding': {keys: ['id','resourceType']},
  'account': {keys: ['account_id','account_name']},
  'acm-certificate': {keys: ['CertificateArn','DomainName','CreatedAt'], enumValues: {'Status': ['ISSUED','PENDING_VALIDATION','INACTIVE','EXPIRED','REVOKED','FAILED','VALIDATION_TIMED_OUT']}},
  'airflow': {keys: ['Name']},
  'alarm': {keys: ['AlarmName','AlarmConfigurationUpdatedTimestamp']},
  'ami': {keys: ['ImageId','Name','CreationDate'], enumValues: {'State': ['available','pending','deregistered','failed','error'],'Architecture': ['x86_64','arm64'],'VirtualizationType': ['hvm','paravirtual']}},
  'apigw-domain-name': {keys: ['domainName','createdDate']},
  'apigwv2': {keys: ['ApiId','name','createdDate']},
  'apigwv2-stage': {keys: ['StageName']},
  'app-elb': {keys: ['LoadBalancerArn','LoadBalancerName','CreatedTime'], enumValues: {'Scheme': ['internet-facing','internal'],'Type': ['application','network','gateway'],'State.Code': ['active','provisioning','active_impaired','failed']}},
  'app-elb-target-group': {keys: ['TargetGroupArn','TargetGroupName']},
  'app-flow': {keys: ['flowName']},
  'asg': {keys: ['AutoScalingGroupName','CreatedTime','LaunchConfigurationName','DesiredCapacity','HealthCheckType'], enumValues: {'HealthCheckType': ['EC2','ELB']}},
  'backup-plan': {keys: ['BackupPlanName','BackupPlanId']},
  'backup-vault': {keys: ['BackupVaultName']},
  'batch-compute': {keys: ['computeEnvironmentName']},
  'batch-definition': {keys: ['jobDefinitionName']},
  'batch-queue': {keys: ['jobQueueName']},
  'cache-cluster': {keys: ['CacheClusterId','CacheClusterCreateTime'], enumValues: {'CacheClusterStatus': ['available','creating','deleted','deleting','modifying','snapshotting'],'Engine': ['memcached','redis']}},
  'cache-snapshot': {keys: ['SnapshotName','StartTime']},
  'cfn': {keys: ['StackName','CreationTime'], enumValues: {'StackStatus': ['CREATE_COMPLETE','UPDATE_COMPLETE','DELETE_FAILED','ROLLBACK_COMPLETE','CREATE_FAILED','DELETE_COMPLETE','UPDATE_ROLLBACK_COMPLETE']}},
  'cloudtrail': {keys: ['TrailARN','Name'], enumValues: {'IsMultiRegionTrail': ['true','false'],'LogFileValidationEnabled': ['true','false']}},
  'codebuild': {keys: ['name','created']},
  'codecommit': {keys: ['repositoryName','creationDate']},
  'codepipeline': {keys: ['name','created']},
  'config-rule': {keys: ['ConfigRuleName']},
  'customer-gateway': {keys: ['CustomerGatewayId']},
  'dax': {keys: ['ClusterName']},
  'directconnect': {keys: ['connectionId','connectionName']},
  'directory': {keys: ['DirectoryId','Name']},
  'distribution': {keys: ['Id','DomainName','LastModifiedTime'], enumValues: {'Status': ['Deployed','InProgress'],'HttpVersion': ['http1.1','http2','http2and3']}},
  'dynamodb-table': {keys: ['TableName','CreationDateTime'], enumValues: {'TableStatus': ['ACTIVE','CREATING','DELETING','UPDATING'],'BillingModeSummary.BillingMode': ['PAY_PER_REQUEST','PROVISIONED']}},
  'ebs': {keys: ['VolumeId','createTime','Attachments[0].InstanceId','Size','VolumeType','KmsKeyId','State','Encrypted'], enumValues: {'State': ['available','in-use','creating','deleting','error'],'VolumeType': ['gp2','gp3','io1','io2','st1','sc1','standard'],'Encrypted': ['true','false']}},
  'ebs-snapshot': {keys: ['SnapshotId','StartTime','VolumeId','VolumeSize','State'], enumValues: {'State': ['pending','completed','error']}},
  'ec2': {keys: ['InstanceId','PublicDnsName','LaunchTime','InstanceType','State.Name','VpcId','PrivateIpAddress','Architecture','Placement.Tenancy'], enumValues: {'State.Name': ['running','stopped','terminated','pending','stopping','shutting-down'],'InstanceType': ['t3.micro','t3.small','t3.medium','t3.large','t3.xlarge','m5.large','m5.xlarge','c5.large','r5.large'],'Architecture': ['x86_64','arm64'],'Placement.Tenancy': ['default','dedicated','host']}},
  'ec2-reserved': {keys: ['ReservedInstancesId','Start']},
  'ecr': {keys: ['repositoryName'], enumValues: {'imageTagMutability': ['MUTABLE','IMMUTABLE']}},
  'ecs': {keys: ['clusterArn','clusterName'], enumValues: {'status': ['ACTIVE','PROVISIONING','FAILED','UNAVAILABLE','DELETE_IN_PROGRESS']}},
  'ecs-service': {keys: ['serviceArn','serviceName'], enumValues: {'status': ['ACTIVE','DRAINING','INACTIVE']}},
  'ecs-task': {keys: ['taskArn']},
  'ecs-task-definition': {keys: ['taskDefinitionArn']},
  'efs': {keys: ['FileSystemId','Name','CreationTime']},
  'eks': {keys: ['name','createdAt'], enumValues: {'status': ['ACTIVE','CREATING','DELETING','FAILED','UPDATING','PENDING']}},
  'eks-nodegroup': {keys: ['nodegroupArn','nodegroupName','createdAt']},
  'elastic-ip': {keys: ['AllocationId','PublicIp']},
  'elasticache-group': {keys: ['ReplicationGroupId']},
  'elasticbeanstalk': {keys: ['ApplicationName']},
  'elasticbeanstalk-environment': {keys: ['EnvironmentName']},
  'elasticsearch': {keys: ['DomainName','Name'], enumValues: {'ElasticsearchClusterConfig.DedicatedMasterEnabled': ['true','false']}},
  'elb': {keys: ['LoadBalancerName','DNSName','CreatedTime','VPCId'], enumValues: {'Scheme': ['internet-facing','internal']}},
  'emr': {keys: ['Id','Name','Status.Timeline.CreationDateTime'], enumValues: {'Status.State': ['STARTING','BOOTSTRAPPING','RUNNING','WAITING','TERMINATING','TERMINATED','TERMINATED_WITH_ERRORS']}},
  'eni': {keys: ['NetworkInterfaceId','Status','InterfaceType'], enumValues: {'Status': ['available','in-use','associated','attaching','detaching'],'InterfaceType': ['interface','natGateway','efa','trunk']}},
  'event-bus': {keys: ['Name']},
  'firehose': {keys: ['DeliveryStreamName','CreateTimestamp'], enumValues: {'DeliveryStreamStatus': ['CREATING','DELETING','ACTIVE']}},
  'fsx': {keys: ['FileSystemId','CreationTime']},
  'glacier': {keys: ['VaultName']},
  'glue-crawler': {keys: ['Name','CreatedOn']},
  'glue-database': {keys: ['Name','CreatedOn']},
  'glue-job': {keys: ['Name','CreatedOn']},
  'guardduty-finding': {keys: ['AccountId','Description']},
  'hostedzone': {keys: ['Id','Name']},
  'iam-group': {keys: ['GroupName','CreateDate']},
  'iam-policy': {keys: ['PolicyId','PolicyName','CreateDate']},
  'iam-role': {keys: ['RoleName','CreateDate']},
  'iam-user': {keys: ['UserName','CreateDate']},
  'internet-gateway': {keys: ['InternetGatewayId']},
  'kafka': {keys: ['ClusterArn','ClusterName','CreationTime']},
  'kinesis': {keys: ['StreamName'], enumValues: {'StreamStatus': ['ACTIVE','CREATING','DELETING','UPDATING']}},
  'kms-key': {keys: ['KeyId'], enumValues: {'KeyState': ['Enabled','Disabled','PendingDeletion','PendingImport'],'KeyManager': ['AWS','CUSTOMER'],'KeyUsage': ['ENCRYPT_DECRYPT','SIGN_VERIFY']}},
  'lambda': {keys: ['FunctionName','LastModified','State','Runtime','PackageType'], enumValues: {'State': ['Active','Inactive','Pending','Failed'],'Runtime': ['python3.9','python3.10','python3.11','python3.12','nodejs18.x','nodejs20.x','java11','java17','dotnet6','go1.x'],'PackageType': ['Zip','Image']}},
  'lambda-layer': {keys: ['LayerName']},
  'log-group': {keys: ['logGroupName','creationTime']},
  'nat-gateway': {keys: ['NatGatewayId','CreateTime'], enumValues: {'State': ['available','deleted','deleting','failed','pending']}},
  'network-acl': {keys: ['NetworkAclId']},
  'peering-connection': {keys: ['VpcPeeringConnectionId']},
  'qldb': {keys: ['Name','CreationDateTime']},
  'r53domain': {keys: ['DomainName']},
  'rds': {keys: ['DBInstanceIdentifier','Endpoint.Address','InstanceCreateTime','DBName','Engine','EngineVersion','MultiAZ','AllocatedStorage','StorageEncrypted','PubliclyAccessible'], enumValues: {'DBInstanceStatus': ['available','stopped','starting','stopping','creating','deleting','modifying','rebooting','backing-up'],'Engine': ['mysql','postgres','mariadb','oracle-ee','sqlserver-ee','aurora','aurora-mysql','aurora-postgresql'],'StorageType': ['gp2','gp3','io1','standard'],'MultiAZ': ['true','false'],'StorageEncrypted': ['true','false'],'PubliclyAccessible': ['true','false']}},
  'rds-cluster': {keys: ['DBClusterIdentifier'], enumValues: {'Status': ['available','creating','deleting','modifying','stopped','stopping','starting']}},
  'rds-cluster-snapshot': {keys: ['DBClusterSnapshotIdentifier','SnapshotCreateTime']},
  'rds-snapshot': {keys: ['DBSnapshotIdentifier','SnapshotCreateTime'], enumValues: {'Status': ['available','creating','deleting','failed','copying'],'StorageEncrypted': ['true','false']}},
  'redshift': {keys: ['ClusterIdentifier','ClusterCreateTime'], enumValues: {'ClusterStatus': ['available','creating','deleting','modifying','paused']}},
  'redshift-snapshot': {keys: ['SnapshotIdentifier','SnapshotCreateTime']},
  'rest-api': {keys: ['id','name','createdDate']},
  'rest-stage': {keys: ['deploymentId','stageName','createdDate']},
  'route-table': {keys: ['RouteTableId']},
  's3': {keys: ['Name','CreationDate'], enumValues: {'LocationConstraint': ['us-east-1','us-east-2','us-west-1','us-west-2','ap-south-1','ap-southeast-1','ap-southeast-2','ap-northeast-1','eu-west-1','eu-central-1']}},
  'sagemaker-endpoint': {keys: ['EndpointArn','EndpointName','CreationTime']},
  'sagemaker-notebook': {keys: ['NotebookInstanceArn','NotebookInstanceName','CreationTime']},
  'secrets-manager': {keys: ['Name'], enumValues: {'RotationEnabled': ['true','false']}},
  'security-group': {keys: ['GroupId','GroupName']},
  'sns': {keys: ['TopicArn','DisplayName']},
  'sns-subscription': {keys: ['SubscriptionArn','Protocol','Endpoint','TopicArn']},
  'sqs': {keys: ['QueueUrl','CreatedTimestamp','QueueArn','ApproximateNumberOfMessages'], enumValues: {'FifoQueue': ['true','false']}},
  'ssm-parameter': {keys: ['Name'], enumValues: {'Type': ['String','StringList','SecureString']}},
  'step-machine': {keys: ['stateMachineArn','name','creationDate'], enumValues: {'status': ['ACTIVE','DELETING']}},
  'subnet': {keys: ['SubnetId'], enumValues: {'State': ['available','pending'],'MapPublicIpOnLaunch': ['true','false'],'DefaultForAz': ['true','false']}},
  'transit-gateway': {keys: ['TransitGatewayId']},
  'vpc': {keys: ['VpcId'], enumValues: {'State': ['available','pending'],'IsDefault': ['true','false'],'InstanceTenancy': ['default','dedicated']}},
  'vpc-endpoint': {keys: ['VpcEndpointId','CreationTimestamp']},
  'vpn-connection': {keys: ['VpnConnectionId']},
  'vpn-gateway': {keys: ['VpnGatewayId']},
  'wafv2': {keys: ['Id','Name'], enumValues: {'Scope': ['REGIONAL','CLOUDFRONT']}},
  'workspaces': {keys: ['WorkspaceId']},
}

// Fields too complex to render as simple inputs
const SKIP_FIELDS = new Set([
  'value_from','value_type','value_types','value_regex',
  'value_path','default','attrs','whitelist_from',
  'whitelist_orgids_from','whitelist_vpce_from','whitelist_vpc_from',
])

const SEVERITY_COLORS = {
  CRITICAL: 'bg-red-100 text-red-700 border-red-200',
  HIGH:     'bg-orange-100 text-orange-700 border-orange-200',
  WARNING:  'bg-yellow-100 text-yellow-700 border-yellow-200',
  MEDIUM:   'bg-yellow-50 text-yellow-600 border-yellow-200',
  COST:     'bg-violet-100 text-violet-700 border-violet-200',
  LOW:      'bg-gray-100 text-gray-600 border-gray-200',
  INFO:     'bg-blue-50 text-blue-600 border-blue-200',
}

// Wraps matched substring in a highlight span
function highlightMatch(text, query) {
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <span className="text-blue-600 font-semibold">{text.slice(idx, idx + query.length)}</span>
      {text.slice(idx + query.length)}
    </>
  )
}

export default function PolicyBuilder() {
  const [schema, setSchema]         = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)

  // form state
  const [authType, setAuthType]     = useState('access-key')
  const [region, setRegion]         = useState('ap-south-1')
  const [selectedResource, setSelectedResource] = useState('')
  const [filters, setFilters]       = useState([])
  const [actions, setActions]       = useState([])
  const [policyName, setPolicyName] = useState('')

  // save / edit state
  const [savedRules,    setSavedRules]    = useState(() => getUserRules())
  const [editingRuleId, setEditingRuleId] = useState(null)
  const [showSaveForm,  setShowSaveForm]  = useState(false)
  const [saveForm,      setSaveForm]      = useState({ label:'', category:'security', customCategory:'', severity:'INFO', group:'', customGroup:'', description:'', recommendation:'' })
  const [saveMsg,       setSaveMsg]       = useState(null)

  // run state
  const [running,         setRunning]         = useState(false)
  const [report,          setReport]          = useState(null)
  const [extraPolicyInfo, setExtraPolicyInfo] = useState(null)
  const [runError,        setRunError]        = useState(null)

  // Load CSV once
  useEffect(() => {
    fetch('/c7n_schema.csv')
      .then(r => { if (!r.ok) throw new Error('Failed to load schema'); return r.text() })
      .then(text => { setSchema(parseCSV(text)); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  // Derived lists
  const serviceGroups = useMemo(() => {
    const groups = {}
    schema.forEach(row => {
      if (!groups[row.service_group]) groups[row.service_group] = new Set()
      groups[row.service_group].add(row.resource)
    })
    return Object.fromEntries(
      Object.entries(groups)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([g, set]) => [g, [...set].sort()])
    )
  }, [schema])

  const availableFilters = useMemo(() =>
    schema.filter(r => r.resource === selectedResource && r.category === 'filter')
      .sort((a, b) => a.name.localeCompare(b.name))
  , [schema, selectedResource])

  const availableActions = useMemo(() =>
    schema.filter(r => r.resource === selectedResource && r.category === 'action')
      .sort((a, b) => a.name.localeCompare(b.name))
  , [schema, selectedResource])

  // ── Handlers ────────────────────────────────────────────────────
  function selectResource(res) {
    setSelectedResource(res)
    setFilters([])
    setActions([])
    setReport(null)
    setExtraPolicyInfo(null)
    setPolicyName(`dynamic-${res}`)
  }

  function addFilter(name) {
    if (filters.some(f => f.type === name)) return
    const schemaRow = availableFilters.find(r => r.name === name)
    let defaultParams = {}
    if (schemaRow?.params_json) {
      try {
        const ps = JSON.parse(schemaRow.params_json)
        if (ps.properties) {
          Object.entries(ps.properties).forEach(([k]) => {
            if (k === 'type') return
            defaultParams[k] = k === 'op' ? 'eq' : ''
          })
        }
      } catch {}
    }
    if (Object.keys(defaultParams).length === 0) {
      defaultParams = { key: '', op: 'eq', value: '' }
    }
    const schemaForInit = availableFilters.find(r => r.name === name)
    let required = []
    if (schemaForInit?.params_json) {
      try {
        const ps = JSON.parse(schemaForInit.params_json)
        required = (ps.required || []).filter(k => k !== 'type')
      } catch {}
    }
    setFilters(prev => [...prev, { type: name, params: defaultParams, required }])
  }

  function removeFilter(idx) {
    setFilters(prev => prev.filter((_, i) => i !== idx))
  }

  function updateFilterParam(idx, key, val) {
    setFilters(prev => prev.map((f, i) =>
      i === idx ? { ...f, params: { ...f.params, [key]: val } } : f
    ))
  }

  function addAction(name) {
    if (actions.some(a => a.type === name)) return
    setActions(prev => [...prev, { type: name, params: {} }])
  }

  function removeAction(idx) {
    setActions(prev => prev.filter((_, i) => i !== idx))
  }

  // Build the spec object
  function buildSpec() {
    const builtFilters = filters.map(f => {
      const obj = { type: f.type }
      Object.entries(f.params).forEach(([k, v]) => {
        if (v === '' || v === null || v === undefined) return
        if (v === true || v === false) { obj[k] = v; return }
        if (v === 'true')  { obj[k] = true;  return }
        if (v === 'false') { obj[k] = false; return }
        const n = Number(v)
        obj[k] = Number.isFinite(n) && v !== '' ? n : v
      })
      return obj
    })
    const builtActions = actions.map(a => ({ type: a.type, ...a.params }))
    return {
      name:     policyName || `dynamic-${selectedResource}`,
      resource: selectedResource,
      filters:  builtFilters,
      actions:  builtActions,
    }
  }

  // Generate YAML preview (client-side approximation)
  function previewYaml() {
    if (!selectedResource) return '# Select a resource type to begin'
    const spec = buildSpec()
    const filtersYaml = spec.filters.map(f => {
      const lines = Object.entries(f)
        .map(([k, v]) => `      ${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
        .join('\n')
      return `    - ${lines.trim().replace(/^  /, '')}`
    }).join('\n')
    const actionsYaml = spec.actions.map(a => {
      return `    - type: ${a.type}`
    }).join('\n')
    return `policies:\n  - name: ${spec.name}\n    resource: aws.${spec.resource}\n    filters:\n${filtersYaml || '      []'}\n    actions:\n${actionsYaml || '      []'}`
  }

  // Plain-English description
  function buildDescription() {
    if (!selectedResource) return ''
    const parts = [`Find all aws.${selectedResource} resources`]
    filters.forEach(f => {
      if (f.params.key && f.params.value) {
        parts.push(`where ${f.params.key} ${f.params.op || 'eq'} "${f.params.value}"`)
      } else {
        parts.push(`matching filter: ${f.type}`)
      }
    })
    if (actions.length > 0) {
      parts.push(`then: ${actions.map(a => a.type).join(', ')}`)
    }
    return parts.join(' · ')
  }

  // ── Save / Edit / Delete handlers ───────────────────────────────
  function openSaveForm() {
    const existingRule = savedRules.find(r => r.id === editingRuleId)
    setSaveForm({
      label:          existingRule?.label          || policyName || `dynamic-${selectedResource}`,
      category:       existingRule?.category       || 'security',
      customCategory: '',
      severity:       existingRule?.severity       || 'INFO',
      group:          existingRule?.group          || '',
      customGroup:    '',
      description:    existingRule?.description    || '',
      recommendation: existingRule?.recommendation || '',
    })
    setShowSaveForm(true)
    setSaveMsg(null)
  }

  function applyQuickFill() {
    // Find POLICY_DESC entries that match the selected resource/service
    const meta = C7N_RESOURCE_META[selectedResource] || {}
    const svc  = meta.service?.toLowerCase()
    const candidates = Object.entries(POLICY_DESC).filter(([name]) => {
      const info = POLICY_INFO[name]
      return info && info.service?.toLowerCase() === svc
    })
    if (candidates.length === 0) return
    const [, d] = candidates[0]
    setSaveForm(f => ({
      ...f,
      description:    f.description    || d.desc           || '',
      recommendation: f.recommendation || d.recommendation || '',
    }))
  }

  function handleSaveRule() {
    const spec     = buildSpec()
    const meta     = C7N_RESOURCE_META[selectedResource] || { service:'other', resourceType: selectedResource }
    const category = saveForm.category === '__custom__'
      ? saveForm.customCategory.trim().toLowerCase().replace(/\s+/g, '-')
      : saveForm.category
    const group = saveForm.group === '__new__'
      ? saveForm.customGroup.trim()
      : saveForm.group

    if (!category) { setSaveMsg({ ok:false, text:'Category is required' }); return }

    const rule = saveUserRule({
      id:             editingRuleId || undefined,
      name:           spec.name,
      label:          saveForm.label || spec.name,
      category,
      severity:       saveForm.severity,
      group:          group || undefined,
      description:    saveForm.description.trim()    || undefined,
      recommendation: saveForm.recommendation.trim() || undefined,
      service:        meta.service,
      resourceType:   meta.resourceType,
      spec,
    })
    setSavedRules(getUserRules())
    setEditingRuleId(rule.id)
    setShowSaveForm(false)
    setSaveMsg({ ok:true, text: editingRuleId ? 'Rule updated' : 'Rule saved' })
    setTimeout(() => setSaveMsg(null), 3000)
  }

  function handleDeleteRule(id) {
    deleteUserRule(id)
    setSavedRules(getUserRules())
    if (editingRuleId === id) {
      setEditingRuleId(null)
      setSaveMsg(null)
    }
  }

  function handleLoadForEdit(rule) {
    setPolicyName(rule.spec.name || '')
    setSelectedResource(rule.spec.resource)
    const uiFilters = (rule.spec.filters || []).map(f => {
      const { type, ...params } = f
      return { type, params, required: [] }
    })
    const uiActions = (rule.spec.actions || []).map(a => {
      const { type, ...params } = a
      return { type, params }
    })
    setFilters(uiFilters)
    setActions(uiActions)
    setEditingRuleId(rule.id)
    setShowSaveForm(false)
    setSaveMsg({ ok:true, text:`Loaded "${rule.label}" for editing` })
    setTimeout(() => setSaveMsg(null), 3000)
  }

  async function runScan() {
    const spec = buildSpec()
    setRunning(true)
    setRunError(null)
    setReport(null)
    setExtraPolicyInfo(null)
    try {
      const res = await runBuild(spec, { dryrun: true, region, authType })

      const wrappedReport = {
        results: [res],
        account: { account_id: 'builder', region },
        region,
        dryrun: true,
      }
      setReport(wrappedReport)

      const meta = C7N_RESOURCE_META[spec.resource] || { service: 'other', resourceType: spec.resource }
      setExtraPolicyInfo({
        [res.policy]: {
          service:      meta.service,
          resourceType: meta.resourceType,
          category:     'security',
          severity:     'INFO',
          label:        spec.name || `dynamic-${spec.resource}`,
        },
      })

      saveToHistory(`builder:${spec.resource}`, wrappedReport)
    } catch (e) {
      setRunError(e.message)
    } finally {
      setRunning(false)
    }
  }

  // ── Search state ─────────────────────────────────────────────────
  const [resourceSearch, setResourceSearch] = useState('')

  const filteredGroups = useMemo(() => {
    const q = resourceSearch.trim().toLowerCase()
    if (!q) return serviceGroups
    const result = {}
    for (const [group, resources] of Object.entries(serviceGroups)) {
      const matched = resources.filter(r => r.toLowerCase().includes(q))
      if (matched.length > 0) result[group] = matched
    }
    return result
  }, [serviceGroups, resourceSearch])

  const resourceCount  = Object.values(serviceGroups).reduce((s, r) => s + r.length, 0)
  const filteredCount  = Object.values(filteredGroups).reduce((s, r) => s + r.length, 0)

  // ── Early returns after all hooks ───────────────────────────────
  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-500">
      Loading c7n schema…
    </div>
  )
  if (error) return (
    <div className="p-6 text-red-600">Schema load error: {error}</div>
  )

  return (
    <div className="flex h-full">
      {/* ── Left panel: resource selector (40% on desktop) ── */}
      <aside className="w-64 border-r border-gray-200 bg-white flex-shrink-0 flex flex-col">

        {/* Header + search */}
        <div className="p-3 border-b border-gray-200 flex-shrink-0">
          <h2 className="text-sm font-semibold text-gray-800 mb-2">Resource Type</h2>
          <div className="relative">
            <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none"
              fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/>
            </svg>
            <input
              value={resourceSearch}
              onChange={e => setResourceSearch(e.target.value)}
              placeholder="Search resources…"
              className="w-full pl-7 pr-7 py-1.5 text-xs bg-gray-50 border border-gray-300 rounded-lg text-gray-700 placeholder-gray-400 focus:outline-none focus:border-blue-500"
            />
            {resourceSearch && (
              <button
                onClick={() => setResourceSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs leading-none"
              >✕</button>
            )}
          </div>
          <p className="text-[10px] text-gray-400 mt-1.5">
            {resourceSearch
              ? `${filteredCount} of ${resourceCount} resources`
              : `${resourceCount} resources`}
          </p>
        </div>

        {/* Scrollable resource list */}
        <div className="overflow-y-auto flex-1">
          {Object.keys(filteredGroups).length === 0 ? (
            <p className="px-4 py-6 text-xs text-gray-400 text-center">No resources match "{resourceSearch}"</p>
          ) : (
            Object.entries(filteredGroups).map(([group, resources]) => (
              <div key={group}>
                <div className="px-4 py-1.5 text-[10px] font-bold uppercase text-gray-400 tracking-wider bg-gray-50 sticky top-0 z-10 border-b border-gray-100">
                  {group}
                </div>
                {resources.map(res => (
                  <button
                    key={res}
                    onClick={() => selectResource(res)}
                    className={`w-full text-left px-4 py-1.5 text-xs transition-colors ${
                      selectedResource === res
                        ? 'bg-blue-50 text-blue-700 font-medium'
                        : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                    }`}
                  >
                    {resourceSearch
                      ? highlightMatch(res, resourceSearch)
                      : res}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </aside>

      {/* ── Split: builder (60%) + YAML preview (40%) ── */}
      <div className="flex-1 flex min-w-0">

        {/* Builder panel */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 min-w-0">
          {!selectedResource ? (
            <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
              Select a resource type from the left panel
            </div>
          ) : (
            <>
              {/* Header row */}
              <div className="flex items-center gap-3 flex-wrap">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">
                    aws.<span className="text-blue-600">{selectedResource}</span>
                  </h2>
                  <p className="text-xs text-gray-500">
                    {availableFilters.length} filters · {availableActions.length} actions
                    {editingRuleId && <span className="ml-2 text-blue-600">· editing saved rule</span>}
                  </p>
                </div>
                <div className="ml-auto flex items-center gap-2 flex-wrap">
                  <select value={authType} onChange={e => setAuthType(e.target.value)}
                    className="bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500">
                    <option value="access-key">Access Key (local)</option>
                    <option value="iam-role">IAM Role (Lambda)</option>
                  </select>
                  <input value={region} onChange={e => setRegion(e.target.value)}
                    placeholder="region"
                    className="bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 w-36 focus:outline-none focus:border-blue-500"/>
                  <input value={policyName} onChange={e => setPolicyName(e.target.value)}
                    placeholder="policy name"
                    className="bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 w-44 focus:outline-none focus:border-blue-500"/>
                </div>
              </div>

              {/* Save feedback message */}
              {saveMsg && (
                <div className={`text-xs px-3 py-2 rounded-lg border ${saveMsg.ok
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : 'bg-red-50 text-red-600 border-red-200'}`}>
                  {saveMsg.text}
                </div>
              )}

              {/* ── Saved Rules list — compact cards ── */}
              {savedRules.length > 0 && (
                <SavedRulesList
                  rules={savedRules}
                  editingId={editingRuleId}
                  onEdit={handleLoadForEdit}
                  onDelete={handleDeleteRule}
                />
              )}

              {/* ── Save Rule form ── */}
              {showSaveForm && (
                <div className="card p-4 border-blue-200 space-y-3">
                  <h3 className="text-xs font-semibold text-blue-700 uppercase tracking-wider">
                    {editingRuleId ? 'Update Saved Rule' : 'Save as Custom Rule'}
                  </h3>
                  <div className="space-y-3">
                    {/* Label */}
                    <div>
                      <label className="text-[10px] text-gray-500 block mb-1">Display Label <span className="text-red-400">*</span></label>
                      <input
                        value={saveForm.label}
                        onChange={e => setSaveForm(f => ({ ...f, label: e.target.value }))}
                        placeholder="e.g. Stopped EC2 instances"
                        className="w-full bg-white border border-gray-300 text-gray-800 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                      />
                    </div>

                    {/* Category + Severity */}
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[10px] text-gray-500 block mb-1">Category</label>
                        <select
                          value={saveForm.category}
                          onChange={e => setSaveForm(f => ({ ...f, category: e.target.value }))}
                          className="w-full bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                        >
                          <option value="security">Security</option>
                          <option value="cost">Cost Optimisation</option>
                          {getUserCategories().map(c => <option key={c} value={c}>{c}</option>)}
                          <option value="__custom__">+ New category…</option>
                        </select>
                        {saveForm.category === '__custom__' && (
                          <input
                            value={saveForm.customCategory}
                            onChange={e => setSaveForm(f => ({ ...f, customCategory: e.target.value }))}
                            placeholder="e.g. compliance"
                            className="mt-1 w-full bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                          />
                        )}
                      </div>
                      <div>
                        <label className="text-[10px] text-gray-500 block mb-1">Severity</label>
                        <select
                          value={saveForm.severity}
                          onChange={e => setSaveForm(f => ({ ...f, severity: e.target.value }))}
                          className="w-full bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                        >
                          {['CRITICAL','HIGH','WARNING','MEDIUM','COST','LOW','INFO'].map(s =>
                            <option key={s} value={s}>{s}</option>
                          )}
                        </select>
                      </div>
                    </div>

                    {/* Group */}
                    <div>
                      <label className="text-[10px] text-gray-500 block mb-1">Policy Group <span className="text-gray-400">(optional — organises rules in Policy Library)</span></label>
                      <select
                        value={saveForm.group}
                        onChange={e => setSaveForm(f => ({ ...f, group: e.target.value }))}
                        className="w-full bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                      >
                        <option value="">— No group —</option>
                        {getUserGroups().map(g => <option key={g} value={g}>{g}</option>)}
                        <option value="__new__">+ Create new group…</option>
                      </select>
                      {saveForm.group === '__new__' && (
                        <input
                          value={saveForm.customGroup}
                          onChange={e => setSaveForm(f => ({ ...f, customGroup: e.target.value }))}
                          placeholder="e.g. PCI-DSS, Team-Infra, Q2-Audit"
                          className="mt-1 w-full bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500"
                        />
                      )}
                    </div>

                    {/* Description + Recommendation with quick-fill */}
                    <div className="border-t border-gray-100 pt-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Metadata</span>
                        <button
                          type="button"
                          onClick={applyQuickFill}
                          className="text-[10px] px-2 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-200 hover:bg-blue-100 transition-colors"
                        >
                          ✦ Quick-fill from similar rules
                        </button>
                      </div>
                      <div className="space-y-2">
                        <div>
                          <label className="text-[10px] text-gray-500 block mb-1">What this rule checks</label>
                          <textarea
                            rows={2}
                            value={saveForm.description}
                            onChange={e => setSaveForm(f => ({ ...f, description: e.target.value }))}
                            placeholder="Plain English: what condition does this policy detect?"
                            className="w-full bg-white border border-gray-300 text-gray-800 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500 resize-none"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] text-gray-500 block mb-1">Recommendation</label>
                          <textarea
                            rows={2}
                            value={saveForm.recommendation}
                            onChange={e => setSaveForm(f => ({ ...f, recommendation: e.target.value }))}
                            placeholder="What should an engineer do when this rule triggers?"
                            className="w-full bg-white border border-gray-300 text-gray-800 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-blue-500 resize-none"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button onClick={handleSaveRule}
                      className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded transition-colors">
                      {editingRuleId ? 'Update' : 'Save'}
                    </button>
                    <button onClick={() => setShowSaveForm(false)}
                      className="px-4 py-1.5 bg-white hover:bg-gray-50 text-gray-700 text-xs rounded border border-gray-300 transition-colors">
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* ── Filters ── */}
              <Section title="Filters" count={filters.length}>
                <div className="mb-3">
                  <FilterSearchSelect
                    options={availableFilters}
                    onSelect={addFilter}
                    label="Add filter"
                  />
                </div>
                {filters.length === 0 && (
                  <p className="text-xs text-gray-400 italic">No filters added — add at least one to run a scan.</p>
                )}
                {filters.map((f, idx) => (
                  <FilterRow
                    key={idx}
                    filter={f}
                    resource={selectedResource}
                    schemaRow={availableFilters.find(r => r.name === f.type)}
                    onChange={(key, val) => updateFilterParam(idx, key, val)}
                    onRemove={() => removeFilter(idx)}
                  />
                ))}
              </Section>

              {/* ── Actions ── */}
              <Section title="Actions (optional)" count={actions.length}>
                <div className="mb-3">
                  <FilterSearchSelect
                    options={availableActions}
                    onSelect={addAction}
                    label="Add action"
                  />
                </div>
                {actions.length === 0 && (
                  <p className="text-xs text-gray-400 italic">No actions — scan only (dry-run safe).</p>
                )}
                {actions.map((a, idx) => (
                  <ActionRow
                    key={idx}
                    action={a}
                    onRemove={() => removeAction(idx)}
                  />
                ))}
              </Section>

              {/* ── Error ── */}
              {runError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">
                  {runError}
                </div>
              )}

              {/* ── Results ── */}
              {report && (
                <ReportTable
                  report={report}
                  region={region}
                  authType={authType}
                  extraPolicyInfo={extraPolicyInfo}
                />
              )}
            </>
          )}
        </div>

        {/* ── Right YAML preview pane (sticky) ── */}
        <div className="w-80 border-l border-gray-200 bg-white flex flex-col flex-shrink-0">
          <div className="p-4 border-b border-gray-200 flex-shrink-0">
            <h3 className="text-xs font-bold text-gray-700 uppercase tracking-wide">YAML Preview</h3>
            {selectedResource && (
              <p className="text-[11px] text-gray-400 mt-1 leading-relaxed">{buildDescription()}</p>
            )}
          </div>

          <div className="flex-1 overflow-auto p-4">
            <pre className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs text-green-700 overflow-x-auto whitespace-pre leading-relaxed font-mono">
              {previewYaml()}
            </pre>
          </div>

          {selectedResource && (
            <div className="p-4 border-t border-gray-200 space-y-2 flex-shrink-0">
              <button
                onClick={openSaveForm}
                disabled={filters.length === 0}
                className="w-full px-4 py-2 btn-secondary disabled:opacity-40 disabled:cursor-not-allowed text-center"
              >
                {editingRuleId ? 'Update Rule' : 'Save to Library'}
              </button>
              <button
                onClick={runScan}
                disabled={running || filters.length === 0}
                className="w-full btn-primary justify-center disabled:opacity-40"
              >
                {running
                  ? <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />Scanning…</>
                  : '▶ Test Run'}
              </button>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────

function Section({ title, count, children }) {
  return (
    <div className="card p-4">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
        {title}{count !== undefined && count > 0 ? ` (${count})` : ''}
      </h3>
      {children}
    </div>
  )
}

// ── Tooltip ────────────────────────────────────────────────────────
function Tooltip({ text, children, width = 'w-72' }) {
  const [visible, setVisible] = useState(false)
  if (!text) return children
  return (
    <div className="relative inline-flex items-center"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div className={`absolute bottom-full left-0 mb-2 z-50 ${width} bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-lg pointer-events-none`}>
          <p className="text-[11px] text-gray-600 leading-relaxed">{text}</p>
          <div className="absolute top-full left-4 w-0 h-0 border-x-4 border-x-transparent border-t-4 border-t-gray-200" />
        </div>
      )}
    </div>
  )
}

function FilterSearchSelect({ options, onSelect, label }) {
  const [query, setQuery] = useState('')
  const [open, setOpen]   = useState(false)

  const filtered = useMemo(() =>
    options.filter(o =>
      !query || o.name.toLowerCase().includes(query.toLowerCase()) ||
      (o.doc && o.doc.toLowerCase().includes(query.toLowerCase()))
    ).slice(0, 40)
  , [options, query])

  return (
    <div className="relative">
      <input
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={label}
        className="w-full bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1.5 placeholder-gray-400 focus:outline-none focus:border-blue-500"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-20 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-y-auto">
          {filtered.map(o => (
            <button
              key={o.name}
              onMouseDown={() => { onSelect(o.name); setQuery(''); setOpen(false) }}
              className="w-full text-left px-3 py-2 hover:bg-gray-50 border-b border-gray-100 last:border-0"
            >
              <div className="font-mono text-xs text-blue-600 font-semibold">{o.name}</div>
              {o.doc && (
                <div className="text-[11px] text-gray-500 mt-0.5 leading-relaxed whitespace-normal">
                  {o.doc}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function FilterRow({ filter, resource, schemaRow, onChange, onRemove }) {
  const paramSchema = useMemo(() => {
    if (!schemaRow?.params_json) return null
    try { return JSON.parse(schemaRow.params_json) }
    catch { return null }
  }, [schemaRow])

  const { requiredFields, optionalFields } = useMemo(() => {
    const props = paramSchema?.properties
    if (!props) return { requiredFields: null, optionalFields: null }
    const reqSet = new Set((paramSchema.required || []).filter(k => k !== 'type'))
    const required = []
    const optional = []
    Object.entries(props).forEach(([k, t]) => {
      if (k === 'type') return
      if (SKIP_FIELDS.has(k)) return
      if (reqSet.has(k)) required.push([k, t])
      else optional.push([k, t])
    })
    return { requiredFields: required, optionalFields: optional }
  }, [paramSchema])

  const resAttrs = RESOURCE_ATTRS[resource] || { keys: [], enumValues: {} }

  function renderParam(k, typeSpec) {
    if (SKIP_FIELDS.has(k)) return null

    const val = filter.params[k] ?? ''
    const cls = 'bg-white border border-gray-300 text-gray-700 text-xs rounded px-2 py-1 focus:outline-none focus:border-blue-500'

    if (k === 'key') {
      const knownKeys = resAttrs.keys
      if (knownKeys.length > 0) {
        return (
          <div key="key" className="flex flex-col gap-0.5">
            <label className="text-[10px] text-gray-500">key</label>
            <select
              value={val}
              onChange={e => {
                onChange('key', e.target.value)
                onChange('value', '')
              }}
              className={`${cls} w-52`}
            >
              <option value="">— select attribute —</option>
              {knownKeys.map(k2 => <option key={k2} value={k2}>{k2}</option>)}
              <option value="__custom__">custom (type below)…</option>
            </select>
            {(!val || val === '__custom__' || !knownKeys.includes(val)) && (
              <input
                value={val === '__custom__' ? '' : (knownKeys.includes(val) ? '' : val)}
                onChange={e => onChange('key', e.target.value)}
                placeholder="e.g. State.Name or Tags[0].Key"
                className={`${cls} w-52 mt-0.5`}
              />
            )}
          </div>
        )
      }
      return (
        <div key="key" className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">key</label>
          <input value={val} onChange={e => onChange('key', e.target.value)}
            placeholder="e.g. State.Name" className={`${cls} w-48`} />
        </div>
      )
    }

    if (k === 'value' || (typeof typeSpec === 'string' && typeSpec.includes('/value"'))) {
      const enumVals = resAttrs.enumValues?.[filter.params.key]
      if (enumVals) {
        return (
          <div key="value" className="flex flex-col gap-0.5">
            <label className="text-[10px] text-gray-500">value</label>
            <select value={val} onChange={e => onChange('value', e.target.value)} className={cls}>
              <option value="">— select —</option>
              {enumVals.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
        )
      }
      return (
        <div key="value" className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">value</label>
          <input value={val} onChange={e => onChange('value', e.target.value)}
            placeholder="value" className={`${cls} w-36`} />
        </div>
      )
    }

    if (typeSpec === 'boolean' || (Array.isArray(typeSpec) && typeSpec.includes(true))) {
      return (
        <div key={k} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{k}</label>
          <select value={String(val)}
            onChange={e => onChange(k, e.target.value === 'true' ? true : e.target.value === 'false' ? false : '')}
            className={cls}>
            <option value="">—</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </div>
      )
    }

    if (k === 'op' || (typeof typeSpec === 'string' && typeSpec.includes('comparison_operators'))) {
      return (
        <div key={k} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">op</label>
          <select value={val || 'eq'} onChange={e => onChange('op', e.target.value)} className={cls}>
            {OPS.map(op => <option key={op} value={op}>{op}</option>)}
          </select>
        </div>
      )
    }

    if (Array.isArray(typeSpec)) {
      return (
        <div key={k} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{k}</label>
          <select value={val} onChange={e => onChange(k, e.target.value)} className={cls}>
            <option value="">— select —</option>
            {typeSpec.map(String).map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      )
    }

    if (typeSpec === 'number') {
      return (
        <div key={k} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{k}</label>
          <input type="number" value={val} onChange={e => onChange(k, e.target.value)}
            placeholder="0" className={`${cls} w-24`} />
        </div>
      )
    }

    if (typeof typeSpec === 'string' && typeSpec.startsWith('#/')) return null
    if (typeSpec === 'array' || typeSpec === 'object' || typeSpec === '?') return null

    if (KNOWN_VALUES[k]) {
      return (
        <div key={k} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{k}</label>
          <select value={val} onChange={e => onChange(k, e.target.value)} className={cls}>
            <option value="">— select —</option>
            {KNOWN_VALUES[k].map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      )
    }

    return (
      <div key={k} className="flex flex-col gap-0.5">
        <label className="text-[10px] text-gray-500">{k}</label>
        <input value={val} onChange={e => onChange(k, e.target.value)}
          placeholder={k} className={`${cls} w-40`} />
      </div>
    )
  }

  const hasSchema = requiredFields !== null

  return (
    <div className="mb-2 bg-gray-50 border border-gray-200 rounded-lg">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-200">
        <span className="font-mono text-xs text-blue-600 font-semibold">{filter.type}</span>
        {schemaRow?.doc && (
          <Tooltip text={schemaRow.doc}>
            <span className="w-4 h-4 rounded-full bg-gray-200 text-gray-500 text-[10px] font-bold flex items-center justify-center cursor-default select-none hover:bg-gray-300 hover:text-gray-700 transition-colors">
              ?
            </span>
          </Tooltip>
        )}
        <button onClick={onRemove} className="ml-auto text-gray-400 hover:text-red-500 text-sm leading-none">✕</button>
      </div>

      <div className="px-3 py-2 space-y-2">
        {!hasSchema ? (
          <div>
            <div className="text-[10px] text-red-600 font-semibold uppercase tracking-wider mb-1.5">Required</div>
            <div className="flex flex-wrap gap-2">
              {renderParam('key', 'string')}
              {renderParam('op', 'op')}
              {renderParam('value', 'string')}
            </div>
          </div>
        ) : (
          <>
            {requiredFields.length > 0 && (
              <div>
                <div className="text-[10px] text-red-600 font-semibold uppercase tracking-wider mb-1.5">
                  Required <span className="text-red-500">*</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {requiredFields.map(([k, t]) => (
                    <div key={k} className="relative">
                      {renderParam(k, t)}
                      <span className="absolute -top-0.5 -right-1 text-red-500 text-[10px] font-bold">*</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {optionalFields.length > 0 && (
              <div>
                <div className="text-[10px] text-gray-400 font-semibold uppercase tracking-wider mb-1.5">Optional</div>
                <div className="flex flex-wrap gap-2">
                  {optionalFields.map(([k, t]) => renderParam(k, t))}
                </div>
              </div>
            )}
            {requiredFields.length === 0 && optionalFields.length === 0 && (
              <span className="text-[11px] text-gray-400">(no parameters — filter matches by presence)</span>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function ActionRow({ action, onRemove }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="font-mono text-xs text-violet-700 bg-violet-50 border border-violet-200 rounded px-2 py-1 min-w-[120px]">
        {action.type}
      </span>
      <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
        LIVE action — will execute without dry-run
      </span>
      <button
        onClick={onRemove}
        className="ml-auto text-gray-400 hover:text-red-500 text-xs px-1"
      >✕</button>
    </div>
  )
}

function SavedRulesList({ rules, editingId, onEdit, onDelete }) {
  if (!rules.length) return null
  return (
    <div className="card p-4">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
        Saved Rules ({rules.length})
      </h3>
      <div className="space-y-2">
        {rules.map(rule => {
          const isEditing = rule.id === editingId
          return (
            <div
              key={rule.id}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-colors ${
                isEditing
                  ? 'bg-blue-50 border-blue-200'
                  : 'bg-gray-50 border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-gray-800 truncate">{rule.label || rule.name}</span>
                  {isEditing && (
                    <span className="text-[10px] bg-blue-100 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 font-semibold">
                      editing
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <span className="text-[10px] font-mono text-gray-500">
                    aws.{rule.spec?.resource || rule.resourceType}
                  </span>
                  <span className="text-[10px] text-gray-300">·</span>
                  <span className="text-[10px] bg-gray-100 text-gray-500 border border-gray-200 rounded px-1.5 py-0.5">
                    {rule.category}
                  </span>
                  <span className={`text-[10px] border rounded px-1.5 py-0.5 ${SEVERITY_COLORS[rule.severity] || SEVERITY_COLORS.INFO}`}>
                    {rule.severity}
                  </span>
                  {rule.spec?.filters?.length > 0 && (
                    <span className="text-[10px] text-gray-400">
                      {rule.spec.filters.length} filter{rule.spec.filters.length !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  onClick={() => onEdit(rule)}
                  className="px-2.5 py-1 text-[11px] font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-100 hover:text-gray-800 transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={() => {
                    if (window.confirm(`Delete "${rule.label || rule.name}"?`)) onDelete(rule.id)
                  }}
                  className="px-2.5 py-1 text-[11px] font-medium rounded border border-red-200 text-red-500 hover:bg-red-50 transition-colors"
                >
                  Delete
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
