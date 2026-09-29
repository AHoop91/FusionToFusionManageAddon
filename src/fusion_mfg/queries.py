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
        thumbnail { status signedUrl }
      }
    }
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
    primaryModel {
      drawings(pagination: { limit: 50 }) {
        results {
          id
          name
          itemNumber { id }
          derivatives(derivativeInput: { targetFormat: PDF, generate: false }) { outputFormat status signedUrl }
        }
      }
    }
  }
}
"""

# The whole bill of materials: one flat list of relations down to STRUCTURE_DEPTH
# levels. Each relation names its parent (fromComponent), so the parser rebuilds
# the tree. Results are paged with a cursor.
STRUCTURE_DEPTH = 10
STRUCTURE_PAGE_SIZE = 50

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
