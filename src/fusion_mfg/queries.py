"""GraphQL text for reading one model. Each takes the ``bulkModels`` input list."""

SUMMARY_QUERY = """
query ($input: [BulkModelsQueryInput!]!) {
  bulkModels(input: $input) {
    model {
      id
      component {
        id
        composition
        itemNumber { id }
        description { value }
        partNumber { value }
      }
    }
  }
}
"""

# The Fusion Manage item a component is linked to (the hyperlink on its Item Number in Fusion).
MANAGE_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    lifecycle { itemUrn itemUrl }
  }
}
"""

PROPERTIES_QUERY = """
query ($input: [BulkModelsQueryInput!]!) {
  bulkModels(input: $input) {
    model {
      component {
        allProperties(pagination: { limit: 500 }) {
          results { name displayValue }
        }
      }
    }
  }
}
"""

COMPONENT_PROPERTIES_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    allProperties(pagination: { limit: 500 }) {
      results { name displayValue }
    }
  }
}
"""

# A component's thumbnail alone, so a slow one never holds up the rest. The url is short-lived, so a publish asks for it
# again when it needs it.
THUMBNAIL_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    thumbnail { status signedUrl }
  }
}
"""

# The whole bill of materials: one flat list of relations down to STRUCTURE_DEPTH
# levels. Each relation names its parent (fromComponent), so the parser rebuilds
# the tree. Results are paged with a cursor.
STRUCTURE_DEPTH = 50   # no assembly is assumed to stop at some depth: a read that still reaches this is an error, not a cut-off BOM
# The most a page may hold is 250 ("PaginationInput.limit must be between 1 and 250"), and a page of that size costs 467 of
# the 1000 points a query may cost. Every page has a fixed cost in time (about two seconds with six relations in it), so
# the biggest page is used. How long a full page takes has not been measured.
STRUCTURE_PAGE_SIZE = 250

STRUCTURE_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime, $depth: Int, $cursor: String, $limit: Int) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    bomRelations(depth: $depth, pagination: { cursor: $cursor, limit: $limit }) {
      pagination { cursor }
      results {
        sequenceNumber
        quantityProperty { displayValue }
        fromComponent { id }
        toComponent {
          id
          itemNumber { id }
          name { value }
          description { value }
          partNumber { value }
        }
      }
    }
  }
}
"""
