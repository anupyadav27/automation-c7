"""
Relationship Discovery Engine for CSPM Platform
Discovers relationships between AWS resources based on predefined templates
"""

import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class RelationshipTemplate:
    """Template for discovering a relationship"""
    id: int
    source_resource_type: str
    relation_type: str
    target_resource_type: str
    source_field: List[str]
    source_field_item: Optional[str]
    target_uid_pattern: str
    is_array: bool
    conditional: Optional[str]
    priority: int
    description: Optional[str]


@dataclass
class DiscoveredRelationship:
    """A discovered relationship between two resources"""
    source_uid: str
    source_type: str
    target_uid: str
    target_type: str
    relation_type: str
    confidence: str = 'explicit'
    metadata: Dict[str, Any] = None
    template_id: Optional[int] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class RelationshipDiscoveryEngine:
    """
    Discovers relationships between AWS resources based on templates
    """

    def __init__(self, db_connection=None):
        """
        Initialize the relationship discovery engine

        Args:
            db_connection: Database connection for loading templates
        """
        self.db = db_connection
        self.templates_by_resource_type: Dict[str, List[RelationshipTemplate]] = {}
        self._load_templates()

    def _load_templates(self):
        """Load relationship templates from database"""
        if not self.db:
            logger.warning("No database connection provided, templates not loaded")
            return

        query = """
            SELECT 
                id, source_resource_type, relation_type, target_resource_type,
                source_field, source_field_item, target_uid_pattern, 
                is_array, conditional, priority, description
            FROM resource_relationship_templates
            WHERE enabled = TRUE
            ORDER BY priority ASC
        """

        templates = self.db.execute(query).fetchall()

        for template_data in templates:
            template = RelationshipTemplate(
                id=template_data['id'],
                source_resource_type=template_data['source_resource_type'],
                relation_type=template_data['relation_type'],
                target_resource_type=template_data['target_resource_type'],
                source_field=json.loads(template_data['source_field']),
                source_field_item=template_data['source_field_item'],
                target_uid_pattern=template_data['target_uid_pattern'],
                is_array=template_data['is_array'],
                conditional=template_data['conditional'],
                priority=template_data['priority'],
                description=template_data['description']
            )

            resource_type = template.source_resource_type
            if resource_type not in self.templates_by_resource_type:
                self.templates_by_resource_type[resource_type] = []
            
            self.templates_by_resource_type[resource_type].append(template)

        logger.info(f"Loaded {len(templates)} relationship templates for {len(self.templates_by_resource_type)} resource types")

    def discover_relationships(self, resource: Dict[str, Any]) -> List[DiscoveredRelationship]:
        """
        Discover all relationships for a given resource

        Args:
            resource: Resource dictionary containing uid, resource_type, and resource data

        Returns:
            List of discovered relationships
        """
        relationships = []
        resource_type = resource.get('resource_type')
        resource_uid = resource.get('uid')

        if not resource_type or not resource_uid:
            logger.warning(f"Resource missing resource_type or uid: {resource}")
            return relationships

        # Get applicable templates
        templates = self.templates_by_resource_type.get(resource_type, [])
        
        logger.debug(f"Processing {len(templates)} templates for {resource_type}")

        for template in templates:
            try:
                # Check conditional if exists
                if template.conditional and not self._evaluate_conditional(resource, template.conditional):
                    logger.debug(f"Conditional failed for template {template.id}: {template.conditional}")
                    continue

                # Extract source field value(s)
                values = self._extract_field_value(
                    resource,
                    template.source_field,
                    template.source_field_item,
                    template.is_array
                )

                if not values:
                    logger.debug(f"No values found for template {template.id} field {template.source_field}")
                    continue

                # Generate relationships from extracted values
                for value in values:
                    target_uid = self._generate_target_uid(
                        template.target_uid_pattern,
                        value,
                        resource
                    )

                    if not target_uid:
                        logger.debug(f"Could not generate target UID from pattern {template.target_uid_pattern}")
                        continue

                    relationships.append(DiscoveredRelationship(
                        source_uid=resource_uid,
                        source_type=resource_type,
                        target_uid=target_uid,
                        target_type=template.target_resource_type,
                        relation_type=template.relation_type,
                        confidence='explicit',
                        metadata={
                            'template_id': template.id,
                            'source_field': '.'.join(template.source_field),
                            'description': template.description
                        },
                        template_id=template.id
                    ))

            except Exception as e:
                logger.error(f"Error processing template {template.id} for {resource_type}: {e}", exc_info=True)
                continue

        logger.info(f"Discovered {len(relationships)} relationships for {resource_type} {resource_uid}")
        return relationships

    def _extract_field_value(
        self, 
        resource: Dict[str, Any],
        field_path: List[str],
        item_field: Optional[str] = None,
        is_array: bool = False
    ) -> List[Any]:
        """
        Extract value(s) from nested field path

        Args:
            resource: Resource dictionary
            field_path: List of nested field names
            item_field: For arrays, the field to extract from each item
            is_array: Whether the field contains an array

        Returns:
            List of extracted values
        """
        # Navigate to the field
        value = resource
        for part in field_path:
            if value is None or not isinstance(value, dict):
                return []
            value = value.get(part)

        if value is None:
            return []

        # Handle array fields
        if is_array:
            if not isinstance(value, list):
                logger.warning(f"Expected array for {field_path} but got {type(value)}")
                return []

            if item_field:
                # Extract specific field from each array item
                result = []
                for item in value:
                    extracted = self._get_nested_value(item, item_field)
                    if extracted:
                        result.append(extracted)
                return result
            
            return value

        # Single value
        return [value] if value else []

    def _get_nested_value(self, obj: Any, path: str) -> Any:
        """
        Get nested value from object using dot notation

        Args:
            obj: Object to extract from
            path: Dot-separated path (e.g., 'Ebs.VolumeId')

        Returns:
            Extracted value or None
        """
        if not path:
            return obj

        parts = path.split('.')
        current = obj

        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None

        return current

    def _generate_target_uid(
        self,
        pattern: str,
        value: Any,
        resource: Dict[str, Any]
    ) -> Optional[str]:
        """
        Generate target UID from pattern and value

        Args:
            pattern: UID pattern with placeholders
            value: Extracted value
            resource: Source resource (for metadata like region, account_id)

        Returns:
            Generated UID or None if generation fails
        """
        uid = pattern

        # Handle dict values (for complex extractions)
        if isinstance(value, dict):
            for k, v in value.items():
                placeholder = f'{{{k}}}'
                uid = uid.replace(placeholder, str(v))
        else:
            # For simple values, replace {item} or first placeholder
            if '{item}' in uid:
                uid = uid.replace('{item}', str(value))
            else:
                # Replace first placeholder with value
                match = re.search(r'\{([^}]+)\}', uid)
                if match:
                    uid = uid.replace(match.group(0), str(value), 1)

        # Replace resource metadata placeholders
        uid = uid.replace('{region}', resource.get('region', ''))
        uid = uid.replace('{account_id}', resource.get('account_id', ''))

        # Check if all placeholders are resolved
        if '{' in uid and '}' in uid:
            # Still has unresolved placeholders
            logger.debug(f"Unresolved placeholders in UID: {uid}")
            return None

        return uid

    def _evaluate_conditional(self, resource: Dict[str, Any], condition: str) -> bool:
        """
        Evaluate conditional expression

        Args:
            resource: Resource dictionary
            condition: Conditional expression (e.g., 'StorageEncrypted = TRUE')

        Returns:
            True if condition passes, False otherwise
        """
        try:
            # Simple SQL-like conditionals
            # Examples: 
            # - "StorageEncrypted = TRUE"
            # - "KmsKeyId IS NOT NULL"
            # - "TargetType = 'instance'"
            # - "Protocol = 'lambda'"

            # IS NOT NULL check
            if 'IS NOT NULL' in condition:
                field = condition.split('IS NOT NULL')[0].strip()
                value = self._get_nested_value(resource, field)
                return value is not None

            # IS NULL check
            if 'IS NULL' in condition:
                field = condition.split('IS NULL')[0].strip()
                value = self._get_nested_value(resource, field)
                return value is None

            # LIKE check
            if ' LIKE ' in condition:
                parts = condition.split(' LIKE ')
                field = parts[0].strip()
                pattern = parts[1].strip().strip('"\'')
                value = str(self._get_nested_value(resource, field) or '')
                # Simple wildcard matching
                pattern = pattern.replace('%', '.*')
                return re.match(pattern, value, re.IGNORECASE) is not None

            # Equality check
            if '=' in condition:
                parts = condition.split('=')
                field = parts[0].strip()
                expected = parts[1].strip().strip('"\'')
                
                value = self._get_nested_value(resource, field)
                
                # Handle boolean comparisons
                if expected.upper() in ('TRUE', 'FALSE'):
                    expected = expected.upper() == 'TRUE'
                    return bool(value) == expected
                
                # String comparison
                return str(value) == expected

            # If we can't parse it, log and allow the relationship
            logger.warning(f"Could not parse conditional: {condition}")
            return True

        except Exception as e:
            logger.error(f"Error evaluating conditional '{condition}': {e}")
            # On error, allow the relationship (fail open)
            return True

    def discover_dynamic_relationships(self, resource: Dict[str, Any]) -> List[DiscoveredRelationship]:
        """
        Discover relationships dynamically by scanning for ARN patterns
        This is a fallback for resources without explicit templates

        Args:
            resource: Resource dictionary

        Returns:
            List of inferred relationships
        """
        relationships = []
        resource_uid = resource.get('uid')
        resource_type = resource.get('resource_type')

        if not resource_uid or not resource_type:
            return relationships

        # Recursively find all ARNs in the resource
        arns = self._find_arns_in_dict(resource)

        for arn in arns:
            # Skip self-references
            if arn == resource_uid:
                continue

            # Infer target type from ARN
            target_type = self._infer_resource_type_from_arn(arn)

            relationships.append(DiscoveredRelationship(
                source_uid=resource_uid,
                source_type=resource_type,
                target_uid=arn,
                target_type=target_type or 'unknown',
                relation_type='depends_on',  # Generic relationship
                confidence='inferred',
                metadata={
                    'discovery_method': 'arn_scanning',
                    'note': 'Dynamically discovered from ARN reference'
                }
            ))

        return relationships

    def _find_arns_in_dict(self, obj: Any, arns: Optional[set] = None) -> set:
        """Recursively find all ARNs in a nested dictionary"""
        if arns is None:
            arns = set()

        arn_pattern = r'arn:aws:[a-z0-9\-]+:[a-z0-9\-]*:\d{12}:[^\s]+'

        if isinstance(obj, dict):
            for value in obj.values():
                self._find_arns_in_dict(value, arns)
        elif isinstance(obj, list):
            for item in obj:
                self._find_arns_in_dict(item, arns)
        elif isinstance(obj, str):
            matches = re.findall(arn_pattern, obj)
            arns.update(matches)

        return arns

    def _infer_resource_type_from_arn(self, arn: str) -> Optional[str]:
        """Infer resource type from ARN"""
        # ARN format: arn:aws:service:region:account:resource-type/resource-id
        try:
            parts = arn.split(':')
            if len(parts) >= 6:
                service = parts[2]
                resource_part = ':'.join(parts[5:])
                
                # Extract resource type
                if '/' in resource_part:
                    resource_type = resource_part.split('/')[0]
                elif ':' in resource_part:
                    resource_type = resource_part.split(':')[0]
                else:
                    resource_type = resource_part

                return f"{service}.{resource_type}"
        except Exception:
            pass

        return None
