import { useState, useEffect, useMemo } from 'react'
import { runBuild, getEndpoint } from '../api'
import { saveToHistory } from '../lib/history'
import ReportTable from '../components/ReportTable'

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

// ── Severity colour ────────────────────────────────────────────────
const SEV_CLASS = {
  CRITICAL: 'bg-red-600 text-white',
  HIGH:     'bg-orange-500 text-white',
  WARNING:  'bg-yellow-500 text-black',
  MEDIUM:   'bg-yellow-600 text-white',
  COST:     'bg-violet-600 text-white',
  LOW:      'bg-blue-600 text-white',
  INFO:     'bg-gray-600 text-white',
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

// ── Per-resource attribute keys + enum values (auto-generated from c7n resource_type)
// Covers all 273 c7n AWS resources: id/name/date fields + known enum values
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
  'ebs': {keys: ['VolumeId','createTime','Attachments[0].InstanceId','Size','VolumeType','KmsKeyId'], enumValues: {'State': ['available','in-use','creating','deleting','error'],'VolumeType': ['gp2','gp3','io1','io2','st1','sc1','standard'],'Encrypted': ['true','false']}},
  'ebs-snapshot': {keys: ['SnapshotId','StartTime','VolumeId','VolumeSize','State'], enumValues: {'State': ['pending','completed','error']}},
  'ec2': {keys: ['InstanceId','PublicDnsName','LaunchTime','InstanceType','VpcId','PrivateIpAddress'], enumValues: {'State.Name': ['running','stopped','terminated','pending','stopping','shutting-down'],'InstanceType': ['t3.micro','t3.small','t3.medium','t3.large','t3.xlarge','m5.large','m5.xlarge','c5.large','r5.large'],'Architecture': ['x86_64','arm64'],'Placement.Tenancy': ['default','dedicated','host']}},
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
  'eni': {keys: ['NetworkInterfaceId'], enumValues: {'Status': ['available','in-use','associated','attaching','detaching'],'InterfaceType': ['interface','natGateway','efa','trunk']}},
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
  'lambda': {keys: ['FunctionName','LastModified'], enumValues: {'State': ['Active','Inactive','Pending','Failed'],'Runtime': ['python3.9','python3.10','python3.11','python3.12','nodejs18.x','nodejs20.x','java11','java17','dotnet6','go1.x'],'PackageType': ['Zip','Image']}},
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

export default function PolicyBuilder() {
  const [schema, setSchema]         = useState([])   // all CSV rows
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)

  // form state
  const [authType, setAuthType]     = useState('access-key')
  const [region, setRegion]         = useState('ap-south-1')
  const [selectedResource, setSelectedResource] = useState('')
  const [filters, setFilters]       = useState([])   // [{type,params:{}}]
  const [actions, setActions]       = useState([])   // [{type,params:{}}]
  const [policyName, setPolicyName] = useState('')

  // run state
  const [running, setRunning]       = useState(false)
  const [result, setResult]         = useState(null)
  const [runError, setRunError]     = useState(null)
  const [yamlPreview, setYamlPreview] = useState('')

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
    setResult(null)
    setYamlPreview('')
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
        // booleans come back as actual booleans or 'true'/'false' strings
        if (v === true || v === false) { obj[k] = v; return }
        if (v === 'true')  { obj[k] = true;  return }
        if (v === 'false') { obj[k] = false; return }
        // numeric strings
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

  async function runScan() {
    const spec = buildSpec()
    setRunning(true)
    setRunError(null)
    setResult(null)
    try {
      const res = await runBuild(spec, { dryrun: true, region, authType })
      setResult(res)
      if (res.generated_yaml) setYamlPreview(res.generated_yaml)
      saveToHistory(`builder:${spec.resource}`, { results: [res], dryrun: true, region })
    } catch (e) {
      setRunError(e.message)
    } finally {
      setRunning(false)
    }
  }

  // ── Render ───────────────────────────────────────────────────────
  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-400">
      Loading c7n schema…
    </div>
  )
  if (error) return (
    <div className="p-6 text-red-400">Schema load error: {error}</div>
  )

  const resourceCount = Object.values(serviceGroups).reduce((s, r) => s + r.length, 0)

  return (
    <div className="flex h-full">
      {/* ── Left panel: resource selector ── */}
      <aside className="w-64 border-r border-gray-800 overflow-y-auto bg-gray-900 flex-shrink-0">
        <div className="p-4 border-b border-gray-800">
          <h2 className="text-sm font-semibold text-gray-200">Resource Type</h2>
          <p className="text-[11px] text-gray-500 mt-0.5">{resourceCount} resources</p>
        </div>
        {Object.entries(serviceGroups).map(([group, resources]) => (
          <div key={group}>
            <div className="px-4 py-1.5 text-[10px] font-bold uppercase text-gray-600 tracking-wider bg-gray-900">
              {group}
            </div>
            {resources.map(res => (
              <button
                key={res}
                onClick={() => selectResource(res)}
                className={`w-full text-left px-4 py-1.5 text-xs transition-colors ${
                  selectedResource === res
                    ? 'bg-blue-600/20 text-blue-400 font-medium'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`}
              >
                {res}
              </button>
            ))}
          </div>
        ))}
      </aside>

      {/* ── Main panel ── */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {!selectedResource ? (
          <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
            Select a resource type from the left panel
          </div>
        ) : (
          <>
            {/* Header row */}
            <div className="flex items-center gap-4 flex-wrap">
              <div>
                <h2 className="text-lg font-semibold text-gray-100">
                  aws.<span className="text-blue-400">{selectedResource}</span>
                </h2>
                <p className="text-xs text-gray-500">
                  {availableFilters.length} filters · {availableActions.length} actions
                </p>
              </div>
              <div className="ml-auto flex items-center gap-2 flex-wrap">
                {/* Auth type */}
                <select
                  value={authType}
                  onChange={e => setAuthType(e.target.value)}
                  className="bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1.5"
                >
                  <option value="access-key">Access Key (local)</option>
                  <option value="iam-role">IAM Role (Lambda)</option>
                </select>
                {/* Region */}
                <input
                  value={region}
                  onChange={e => setRegion(e.target.value)}
                  placeholder="region"
                  className="bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1.5 w-36"
                />
                {/* Policy name */}
                <input
                  value={policyName}
                  onChange={e => setPolicyName(e.target.value)}
                  placeholder="policy name"
                  className="bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1.5 w-44"
                />
                {/* Run */}
                <button
                  onClick={runScan}
                  disabled={running || filters.length === 0}
                  className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-semibold rounded transition-colors"
                >
                  {running ? 'Scanning…' : 'Run Scan'}
                </button>
              </div>
            </div>

            {/* ── Filters ── */}
            <Section title="Filters" count={filters.length}>
              {/* Add filter */}
              <div className="mb-3">
                <FilterSearchSelect
                  options={availableFilters}
                  onSelect={addFilter}
                  label="Add filter"
                />
              </div>
              {filters.length === 0 && (
                <p className="text-xs text-gray-600 italic">No filters added — add at least one to run a scan.</p>
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
                <p className="text-xs text-gray-600 italic">No actions — scan only (dry-run safe).</p>
              )}
              {actions.map((a, idx) => (
                <ActionRow
                  key={idx}
                  action={a}
                  onRemove={() => removeAction(idx)}
                />
              ))}
            </Section>

            {/* ── YAML Preview ── */}
            <Section title="YAML Preview">
              <pre className="bg-gray-900 border border-gray-800 rounded p-3 text-xs text-green-400 overflow-x-auto whitespace-pre">
                {yamlPreview || previewYaml()}
              </pre>
            </Section>

            {/* ── Results ── */}
            {runError && (
              <div className="bg-red-900/30 border border-red-700 rounded p-3 text-sm text-red-300">
                {runError}
              </div>
            )}
            {result && (
              <Section title="Scan Results">
                <div className="flex items-center gap-4 mb-3 flex-wrap">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    result.status === 'success' ? 'bg-green-700 text-white' : 'bg-red-700 text-white'
                  }`}>{result.status}</span>
                  <span className="text-xs text-gray-400">
                    {Object.values(result.resources_found || {})[0] ?? 0} resource(s) found
                  </span>
                  <span className="text-xs text-gray-600">policy: {result.policy}</span>
                </div>
                {result.resources && result.resources.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-gray-300">
                      <thead>
                        <tr className="border-b border-gray-800">
                          <th className="text-left py-1.5 px-2 text-gray-500 font-medium">Severity</th>
                          <th className="text-left py-1.5 px-2 text-gray-500 font-medium">Resource ID</th>
                          <th className="text-left py-1.5 px-2 text-gray-500 font-medium">Finding</th>
                          <th className="text-left py-1.5 px-2 text-gray-500 font-medium">Tags</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.resources.map((r, i) => (
                          <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                            <td className="py-1.5 px-2">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${SEV_CLASS[r.Severity] || SEV_CLASS.INFO}`}>
                                {r.Severity}
                              </span>
                            </td>
                            <td className="py-1.5 px-2 font-mono text-gray-300">{r.ResourceId}</td>
                            <td className="py-1.5 px-2 text-gray-400">{r.Finding}</td>
                            <td className="py-1.5 px-2 text-gray-600 text-[11px]">{r.Tags || ''}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 italic">No resources matched the filters.</p>
                )}
                {result.stderr && (
                  <details className="mt-2">
                    <summary className="text-xs text-gray-600 cursor-pointer">stderr output</summary>
                    <pre className="mt-1 text-[11px] text-gray-500 bg-gray-900 rounded p-2 overflow-x-auto">{result.stderr}</pre>
                  </details>
                )}
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────

function Section({ title, count, children }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        {title}{count !== undefined && count > 0 ? ` (${count})` : ''}
      </h3>
      {children}
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
        className="w-full bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1.5 placeholder-gray-600 focus:outline-none focus:border-blue-500"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-20 mt-1 w-full bg-gray-800 border border-gray-700 rounded shadow-xl max-h-56 overflow-y-auto">
          {filtered.map(o => (
            <button
              key={o.name}
              onMouseDown={() => { onSelect(o.name); setQuery(''); setOpen(false) }}
              className="w-full text-left px-3 py-1.5 hover:bg-gray-700 text-xs text-gray-300"
            >
              <span className="font-mono text-blue-400">{o.name}</span>
              {o.doc && <span className="ml-2 text-gray-500 truncate">{o.doc}</span>}
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

  // Split fields into required and optional (both exclude 'type' which is auto-set)
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
    const cls = 'bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1'

    // ── 'key' field: searchable dropdown of resource attribute paths ──
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
                // Reset value when key changes
                onChange('value', '')
              }}
              className={`${cls} w-52`}
            >
              <option value="">— select attribute —</option>
              {knownKeys.map(k2 => <option key={k2} value={k2}>{k2}</option>)}
              <option value="__custom__">custom (type below)</option>
            </select>
            {(!val || val === '__custom__') && (
              <input
                value={val === '__custom__' ? '' : val}
                onChange={e => onChange('key', e.target.value)}
                placeholder="e.g. Tags[0].Key"
                className={`${cls} w-52 mt-0.5`}
              />
            )}
          </div>
        )
      }
      // No known keys — plain text
      return (
        <div key="key" className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">key</label>
          <input value={val} onChange={e => onChange('key', e.target.value)}
            placeholder="e.g. State.Name" className={`${cls} w-48`} />
        </div>
      )
    }

    // ── 'value' field: enum dropdown if key has known values, else text ──
    if (k === 'value' || (typeof typeSpec === 'string' && typeSpec.includes('/value"'))) {
      const enumVals = resAttrs.enumValues[filter.params.key]
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

    // ── boolean ──
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

    // ── op / comparison_operators ──
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

    // ── array in schema → enum dropdown ──
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

    // ── number ──
    if (typeSpec === 'number') {
      return (
        <div key={k} className="flex flex-col gap-0.5">
          <label className="text-[10px] text-gray-500">{k}</label>
          <input type="number" value={val} onChange={e => onChange(k, e.target.value)}
            placeholder="0" className={`${cls} w-24`} />
        </div>
      )
    }

    // ── skip other $ref, array, object, ? ──
    if (typeof typeSpec === 'string' && typeSpec.startsWith('#/')) return null
    if (typeSpec === 'array' || typeSpec === 'object' || typeSpec === '?') return null

    // ── string with known values ──
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

    // ── plain string ──
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
    <div className="mb-2 bg-gray-800/30 border border-gray-800 rounded">
      {/* Filter name header row */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800">
        <span className="font-mono text-xs text-blue-400 font-semibold">{filter.type}</span>
        {schemaRow?.doc && (
          <span className="text-[11px] text-gray-600 truncate" title={schemaRow.doc}>
            — {schemaRow.doc}
          </span>
        )}
        <button onClick={onRemove} className="ml-auto text-gray-600 hover:text-red-400 text-sm leading-none">✕</button>
      </div>

      {/* Params area */}
      <div className="px-3 py-2 space-y-2">
        {!hasSchema ? (
          // No schema — show generic key / op / value
          <div>
            <div className="text-[10px] text-red-400 font-semibold uppercase tracking-wider mb-1.5">Required</div>
            <div className="flex flex-wrap gap-2">
              {renderParam('key', 'string')}
              {renderParam('op', 'op')}
              {renderParam('value', 'string')}
            </div>
          </div>
        ) : (
          <>
            {/* Required fields */}
            {requiredFields.length > 0 && (
              <div>
                <div className="text-[10px] text-red-400 font-semibold uppercase tracking-wider mb-1.5">
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

            {/* Optional fields */}
            {optionalFields.length > 0 && (
              <div>
                <div className="text-[10px] text-gray-600 font-semibold uppercase tracking-wider mb-1.5">Optional</div>
                <div className="flex flex-wrap gap-2">
                  {optionalFields.map(([k, t]) => renderParam(k, t))}
                </div>
              </div>
            )}

            {/* No visible params at all */}
            {requiredFields.length === 0 && optionalFields.length === 0 && (
              <span className="text-[11px] text-gray-600">(no parameters — filter matches by presence)</span>
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
      <span className="font-mono text-xs text-violet-400 bg-violet-950/40 border border-violet-900 rounded px-2 py-1 min-w-[120px]">
        {action.type}
      </span>
      <span className="text-xs text-yellow-600 bg-yellow-900/20 border border-yellow-900/50 rounded px-2 py-0.5">
        LIVE action — will execute without dry-run
      </span>
      <button
        onClick={onRemove}
        className="ml-auto text-gray-600 hover:text-red-400 text-xs px-1"
      >✕</button>
    </div>
  )
}
