"""
Core domain layer.

Contains business entities, ports (abstract interfaces), and value objects.
This layer has NO dependencies on infrastructure (adapters, frameworks, databases).

Subpackages:
- entities/: Business entities (VideoFile, Movie, Series, Episode)
- ports/: Abstract interfaces defining contracts for adapters
- value_objects/: Immutable value objects (Resolution, Codec, Language)
"""
