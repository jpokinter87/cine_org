"""
Application services layer (use cases).

Services orchestrate the domain logic to fulfill application use cases.
They coordinate between entities, ports, and external systems.

This layer contains:
- Use case implementations
- Workflow orchestration
- Transaction management
- Application-level error handling

Services depend on ports (interfaces) from core/, never on concrete
implementations from adapters/.
"""
