# Special Flows: CineOrg

## Configured Skills

| Skill | Priority | When to Invoke | Work Type |
|-------|----------|----------------|-----------|
| /frontend-design | required | Before creating/modifying templates HTML, CSS, layouts | UI/Frontend |
| /code-review | optional | After completing a plan, before merge | Quality |
| /feature-dev | optional | For new features complexes nécessitant analyse d'architecture | Architecture |

## Skill Details

### /frontend-design
**Trigger:** Tout plan impliquant la création ou modification de templates Jinja2, CSS, layouts HTML
**Priority:** Required pour les phases UI
**Notes:** Génère des interfaces avec un design soigné, évite l'esthétique générique AI

### /code-review
**Trigger:** Après complétion d'un plan, pour revue de qualité
**Priority:** Optional
**Notes:** Revue de code pour bugs, sécurité, conventions projet

### /feature-dev
**Trigger:** Nouvelles fonctionnalités complexes nécessitant une analyse d'architecture
**Priority:** Optional
**Notes:** Développement guidé avec compréhension du codebase existant

---
*Created: 2026-02-23*
