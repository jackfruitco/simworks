# Calling a Connector

```aiignore
from simcore.ai.dispatch import call_connector
from chatlab.ai.connectors.patient_initial import generate_patient_initial

# Enqueue (returns AsyncResult)
task = call_connector(generate_patient_initial, sim_id, "hello")
# Immediate (returns final dict)
result = call_connector(generate_patient_initial, sim_id, "hello", enqueue=False)
```