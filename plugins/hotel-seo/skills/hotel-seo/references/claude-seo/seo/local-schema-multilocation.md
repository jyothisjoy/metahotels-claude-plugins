<!-- Ported from claude-seo v2.5.0 (MIT, (c) 2026 agricidaniel), skills/seo/references/local-schema-multilocation.md. Commands rewritten for hotel-seo: claude-seo scripts run through the seo_check MCP tool; hotel rules in ../../hotel-addendum.md win where they differ. -->
# Local Schema: Multi-Location Pattern and Deprecated Types

> Split from `local-schema-types.md`. Load it for multi-location businesses or when validating existing local markup.

## Multi-Location Schema Pattern

```json
// Homepage: Organization with branchOf references
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://example.com/#org",
  "name": "Brand Name",
  "url": "https://example.com"
}

// Each location page: individual LocalBusiness
{
  "@context": "https://schema.org",
  "@type": "Dentist",
  "@id": "https://example.com/locations/downtown/#location",
  "name": "Brand Name - Downtown",
  "branchOf": { "@id": "https://example.com/#org" },
  "address": { ... },
  "geo": { "latitude": "40.71234", "longitude": "-74.00567" },
  "telephone": "+1-555-123-4567",
  "openingHoursSpecification": [ ... ]
}
```

Use `@id` for unique identifiers per location. Subdirectory structure recommended: `domain.com/locations/city-name/` (subdirectory consolidates link equity better than subdomain, Bruce Clay study: 50%+ traffic lift).

---

## Deprecated/Invalid Local Schema

| Type | Status | Date | Use Instead |
|------|--------|------|-------------|
| `Attorney` | Deprecated by Schema.org | -- | `LegalService` + `Person` |
| `VehicleListing` | Rich results removed | June 12, 2025 | `Car` + `Offer` |
| `HowTo` | Rich results removed | September 2023 | None |
| `SpecialAnnouncement` | Deprecated | July 31, 2025 | None |
