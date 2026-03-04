# trainerlab/orca/__init__.py
"""
Trainerlab OrchestrAI components.

This package is a placeholder for future trainer/instructor AI services.
When AI services are needed for trainerlab, they should follow the Pydantic AI
pattern established in chatlab and simulation:

- Services: Use DjangoBaseService with BaseInstruction classes in MRO
- Schemas: Plain Pydantic models with ConfigDict(extra="forbid")
- Persistence: Use BasePersistenceHandler for domain object creation
"""
