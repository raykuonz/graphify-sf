# Test Suite for graphify-sf

Complete test suite for the graphify-sf CLI tool.

## Structure

```
tests/
├── conftest.py                  # Shared fixtures for all tests
├── fixtures/
│   └── simple_project/          # Minimal SFDX project for testing
│       └── force-app/main/default/
│           ├── classes/         # 2 Apex classes
│           ├── triggers/        # 1 Trigger
│           ├── objects/         # 1 Custom object + 1 field
│           ├── flows/           # 1 Flow
│           └── lwc/             # 1 LWC bundle
├── test_detect.py              # Detection module tests
├── test_extract_apex.py        # Apex extraction tests
├── test_extract_flow.py        # Flow extraction tests
├── test_extract_object.py      # Object/field extraction tests
├── test_extract_lwc.py         # LWC extraction tests
├── test_build.py               # Graph building tests
├── test_cluster.py             # Clustering tests
├── test_analyze.py             # Analysis tests
└── test_cli.py                 # End-to-end CLI tests
```

## Running the Tests

### Install Dependencies

First, install the package and test dependencies:

```bash
pip install -e .
pip install pytest
```

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test Files

```bash
pytest tests/test_detect.py -v
pytest tests/test_extract_apex.py -v
pytest tests/test_cli.py -v
```

### Run Specific Tests

```bash
pytest tests/test_detect.py::test_detect_finds_apex_classes -v
```

## Test Coverage

### Detection Tests (`test_detect.py`)
- File type detection (Apex, triggers, flows, objects, fields, LWC)
- Compound suffix matching (.flow-meta.xml, .field-meta.xml, etc.)
- Incremental detection with manifest
- Directory skipping (.sfdx, node_modules, etc.)
- Save/load manifest functionality

### Apex Extraction Tests (`test_extract_apex.py`)
- Class node extraction with correct attributes
- Method extraction and parent relationships
- Trigger extraction with object edges
- Cross-reference detection (_raw_calls)
- SOQL query detection
- DML operation detection
- Confidence levels (EXTRACTED, INFERRED)

### Flow Extraction Tests (`test_extract_flow.py`)
- Flow node extraction
- Process type capture
- Object references in recordUpdates
- Graceful handling of malformed XML
- Confidence levels

### Object Extraction Tests (`test_extract_object.py`)
- Custom object extraction
- Custom field extraction with field_of edges
- Field type capture
- Display label extraction
- Child object metadata (validation rules, etc.)

### LWC Extraction Tests (`test_extract_lwc.py`)
- Component node extraction
- Apex import detection (@salesforce/apex)
- Method extraction
- Child component detection (c-*)
- kebab-case to camelCase conversion

### Build Tests (`test_build.py`)
- Graph creation from extraction
- Node and edge attributes
- Deduplication by label
- Merging multiple extractions
- Directed vs undirected graphs
- Dangling edge handling
- Path normalization

### Cluster Tests (`test_cluster.py`)
- Community detection
- All nodes assigned to communities
- Largest community first (stable ordering)
- Empty/single-node/disconnected graphs
- Cohesion score calculation
- Community splitting for oversized clusters
- Isolated node handling

### Analysis Tests (`test_analyze.py`)
- God nodes (high-degree nodes)
- Method stub filtering
- Surprising connections
- Question generation
- Graph diff (new/removed nodes/edges)
- SF type categorization
- Concept node detection

### CLI Tests (`test_cli.py`)
- Full pipeline execution
- --no-viz flag
- --update incremental mode
- --directed graph creation
- --force overwrite
- query command
- explain command
- path command
- cluster-only command
- Empty project error handling
- Output directory creation
- Valid graph.json format
- Manifest tracking

## Fixtures

The `simple_project` fixture contains a realistic minimal SFDX project:

- **AccountService.cls**: Apex class with 3 methods (SOQL, DML operations)
- **AccountTriggerHandler.cls**: Handler that calls AccountService
- **AccountTrigger.trigger**: Trigger on Account object
- **Account__c.object-meta.xml**: Custom object
- **Status__c.field-meta.xml**: Custom picklist field
- **UpdateAccountStatus.flow-meta.xml**: Flow that updates Account__c
- **accountCard**: LWC component that imports AccountService

This fixture exercises:
- Apex class/method extraction
- Trigger extraction with object edges
- Cross-class method calls
- SOQL and DML detection
- Object and field relationships
- Flow object references
- LWC Apex imports

## Test Philosophy

1. **Independent tests**: Each test is self-contained and doesn't rely on global state
2. **Fixtures over mocks**: Use real data structures (from conftest.py) rather than mocks
3. **Focused assertions**: Tests verify specific behaviors, not just "no exception raised"
4. **Meaningful messages**: Assert statements include helpful failure messages
5. **Fast execution**: Tests use `parallel=False` to avoid process pool overhead

## Adding New Tests

When adding new features:

1. Add fixture data to `tests/fixtures/simple_project/` if needed
2. Create test functions in the appropriate `test_*.py` file
3. Use existing fixtures from `conftest.py` when possible
4. Follow naming convention: `test_<module>_<behavior>`
5. Include docstrings explaining what is being tested

Example:

```python
def test_extract_apex_new_feature(simple_project_path):
    """Test that new feature is extracted correctly."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    assert "new_feature" in result, "Should extract new feature"
```
