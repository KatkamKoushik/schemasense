//! High-performance Schema Diffing and Foreign-Key Dependency Graph Engine.

use petgraph::algo::{tarjan_scc, toposort};
use petgraph::graph::DiGraph;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColumnPayload {
    pub name: String,
    pub data_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForeignKeyPayload {
    #[serde(default)]
    pub constrained_columns: Vec<String>,
    pub referred_table: String,
    #[serde(default)]
    pub referred_columns: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablePayload {
    pub name: String,
    #[serde(default)]
    pub columns: Vec<ColumnPayload>,
    #[serde(default)]
    pub foreign_keys: Vec<ForeignKeyPayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SchemaPayload {
    pub database_name: Option<String>,
    pub dialect: Option<String>,
    pub tables: HashMap<String, TablePayload>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModifiedTableDiff {
    pub added_columns: Vec<String>,
    pub removed_columns: Vec<String>,
    pub type_changes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SchemaDiffResult {
    pub added_tables: Vec<String>,
    pub removed_tables: Vec<String>,
    pub modified_tables: HashMap<String, ModifiedTableDiff>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DependencyAnalysisResult {
    pub is_acyclic: bool,
    pub topological_order: Vec<String>,
    pub cycles: Vec<Vec<String>>,
    pub root_tables: Vec<String>,
    pub leaf_tables: Vec<String>,
}

/// Computes a structural diff between two database schemas.
pub fn diff_schemas_internal(
    old_schema: &SchemaPayload,
    new_schema: &SchemaPayload,
) -> SchemaDiffResult {
    let old_table_names: HashSet<&String> = old_schema.tables.keys().collect();
    let new_table_names: HashSet<&String> = new_schema.tables.keys().collect();

    let mut added_tables: Vec<String> = new_table_names
        .difference(&old_table_names)
        .map(|s| (*s).clone())
        .collect();
    added_tables.sort();

    let mut removed_tables: Vec<String> = old_table_names
        .difference(&new_table_names)
        .map(|s| (*s).clone())
        .collect();
    removed_tables.sort();

    let common_tables: HashSet<&String> = old_table_names
        .intersection(&new_table_names)
        .copied()
        .collect();

    let mut modified_tables: HashMap<String, ModifiedTableDiff> = HashMap::new();

    for table_name in common_tables {
        let old_table = &old_schema.tables[table_name];
        let new_table = &new_schema.tables[table_name];

        let old_cols: HashMap<&str, &str> = old_table
            .columns
            .iter()
            .map(|c| (c.name.as_str(), c.data_type.as_str()))
            .collect();
        let new_cols: HashMap<&str, &str> = new_table
            .columns
            .iter()
            .map(|c| (c.name.as_str(), c.data_type.as_str()))
            .collect();

        let mut added_cols: Vec<String> = new_table
            .columns
            .iter()
            .filter(|c| !old_cols.contains_key(c.name.as_str()))
            .map(|c| c.name.clone())
            .collect();
        added_cols.sort();

        let mut removed_cols: Vec<String> = old_table
            .columns
            .iter()
            .filter(|c| !new_cols.contains_key(c.name.as_str()))
            .map(|c| c.name.clone())
            .collect();
        removed_cols.sort();

        let mut type_changes: Vec<String> = Vec::new();
        for col in &old_table.columns {
            if let Some(&new_type) = new_cols.get(col.name.as_str()) {
                if col.data_type != new_type {
                    type_changes.push(format!("{} ({} -> {})", col.name, col.data_type, new_type));
                }
            }
        }
        type_changes.sort();

        if !added_cols.is_empty() || !removed_cols.is_empty() || !type_changes.is_empty() {
            modified_tables.insert(
                table_name.clone(),
                ModifiedTableDiff {
                    added_columns: added_cols,
                    removed_columns: removed_cols,
                    type_changes,
                },
            );
        }
    }

    SchemaDiffResult {
        added_tables,
        removed_tables,
        modified_tables,
    }
}

/// Builds and analyzes the foreign key dependency directed graph.
pub fn analyze_dependencies_internal(
    tables: &HashMap<String, TablePayload>,
) -> DependencyAnalysisResult {
    let mut graph = DiGraph::<String, ()>::new();
    let mut node_indices = HashMap::new();

    // Deterministic sorted order for nodes
    let mut sorted_table_names: Vec<&String> = tables.keys().collect();
    sorted_table_names.sort();

    for &name in &sorted_table_names {
        let idx = graph.add_node(name.clone());
        node_indices.insert(name.clone(), idx);
    }

    // Add dependency edges: A depends on B if A has an FK referencing B
    // Edge direction: (parent/referred) -> (child/dependent) for topological insertion order
    // Table with no FKs comes first in insertion order
    let mut in_degrees = HashMap::new();
    let mut out_degrees = HashMap::new();
    for name in &sorted_table_names {
        in_degrees.insert((*name).clone(), 0usize);
        out_degrees.insert((*name).clone(), 0usize);
    }

    for (table_name, table_payload) in tables {
        let child_idx = node_indices[table_name];
        for fk in &table_payload.foreign_keys {
            if let Some(&parent_idx) = node_indices.get(&fk.referred_table) {
                // Parent must be inserted before child: edge parent -> child
                graph.add_edge(parent_idx, child_idx, ());
                *out_degrees.get_mut(&fk.referred_table).unwrap() += 1;
                *in_degrees.get_mut(table_name).unwrap() += 1;
            }
        }
    }

    // Root tables: no FK dependencies (in-degree == 0)
    let mut root_tables: Vec<String> = in_degrees
        .iter()
        .filter(|(_, &deg)| deg == 0)
        .map(|(name, _)| name.clone())
        .collect();
    root_tables.sort();

    // Leaf tables: not referenced by other tables (out-degree == 0)
    let mut leaf_tables: Vec<String> = out_degrees
        .iter()
        .filter(|(_, &deg)| deg == 0)
        .map(|(name, _)| name.clone())
        .collect();
    leaf_tables.sort();

    // Cycle detection via Tarjan's Strongly Connected Components
    let sccs = tarjan_scc(&graph);
    let mut cycles = Vec::new();
    for scc in sccs {
        if scc.len() > 1 {
            let mut cycle: Vec<String> = scc.iter().map(|&idx| graph[idx].clone()).collect();
            cycle.sort();
            cycles.push(cycle);
        } else if scc.len() == 1 {
            let idx = scc[0];
            // Check self-loop
            if graph.contains_edge(idx, idx) {
                cycles.push(vec![graph[idx].clone()]);
            }
        }
    }
    cycles.sort();

    let is_acyclic = cycles.is_empty();

    let topological_order = if is_acyclic {
        match toposort(&graph, None) {
            Ok(order) => order.into_iter().map(|idx| graph[idx].clone()).collect(),
            Err(_) => Vec::new(),
        }
    } else {
        Vec::new()
    };

    DependencyAnalysisResult {
        is_acyclic,
        topological_order,
        cycles,
        root_tables,
        leaf_tables,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_schema_diff_internal() {
        let mut old_tables = HashMap::new();
        old_tables.insert(
            "users".to_string(),
            TablePayload {
                name: "users".to_string(),
                columns: vec![
                    ColumnPayload {
                        name: "id".to_string(),
                        data_type: "INTEGER".to_string(),
                    },
                    ColumnPayload {
                        name: "email".to_string(),
                        data_type: "VARCHAR(100)".to_string(),
                    },
                ],
                foreign_keys: vec![],
            },
        );

        let mut new_tables = HashMap::new();
        new_tables.insert(
            "users".to_string(),
            TablePayload {
                name: "users".to_string(),
                columns: vec![
                    ColumnPayload {
                        name: "id".to_string(),
                        data_type: "BIGINT".to_string(),
                    },
                    ColumnPayload {
                        name: "email".to_string(),
                        data_type: "VARCHAR(100)".to_string(),
                    },
                    ColumnPayload {
                        name: "created_at".to_string(),
                        data_type: "TIMESTAMP".to_string(),
                    },
                ],
                foreign_keys: vec![],
            },
        );
        new_tables.insert(
            "orders".to_string(),
            TablePayload {
                name: "orders".to_string(),
                columns: vec![ColumnPayload {
                    name: "id".to_string(),
                    data_type: "INTEGER".to_string(),
                }],
                foreign_keys: vec![],
            },
        );

        let old_schema = SchemaPayload {
            database_name: Some("test_db".to_string()),
            dialect: Some("postgres".to_string()),
            tables: old_tables,
        };
        let new_schema = SchemaPayload {
            database_name: Some("test_db".to_string()),
            dialect: Some("postgres".to_string()),
            tables: new_tables,
        };

        let diff = diff_schemas_internal(&old_schema, &new_schema);
        assert_eq!(diff.added_tables, vec!["orders".to_string()]);
        assert!(diff.removed_tables.is_empty());
        assert!(diff.modified_tables.contains_key("users"));

        let user_diff = &diff.modified_tables["users"];
        assert_eq!(user_diff.added_columns, vec!["created_at".to_string()]);
        assert_eq!(
            user_diff.type_changes,
            vec!["id (INTEGER -> BIGINT)".to_string()]
        );
    }

    #[test]
    fn test_dependency_dag_and_cycles() {
        let mut tables = HashMap::new();
        tables.insert(
            "customers".to_string(),
            TablePayload {
                name: "customers".to_string(),
                columns: vec![],
                foreign_keys: vec![],
            },
        );
        tables.insert(
            "orders".to_string(),
            TablePayload {
                name: "orders".to_string(),
                columns: vec![],
                foreign_keys: vec![ForeignKeyPayload {
                    constrained_columns: vec!["customer_id".to_string()],
                    referred_table: "customers".to_string(),
                    referred_columns: vec!["id".to_string()],
                }],
            },
        );

        let res = analyze_dependencies_internal(&tables);
        assert!(res.is_acyclic);
        assert_eq!(res.cycles.len(), 0);
        assert_eq!(res.root_tables, vec!["customers".to_string()]);
        assert_eq!(res.leaf_tables, vec!["orders".to_string()]);
        assert_eq!(
            res.topological_order,
            vec!["customers".to_string(), "orders".to_string()]
        );
    }
}
