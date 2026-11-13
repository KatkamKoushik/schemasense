//! High-performance SQL AST security validator powered by sqlparser-rs.

use sqlparser::ast::{Expr, Query, SetExpr, SetOperator, Statement, TableFactor, Visit, Visitor};
use sqlparser::dialect::{Dialect, GenericDialect, MySqlDialect, PostgreSqlDialect, SQLiteDialect};
use sqlparser::parser::Parser;
use std::collections::HashSet;
use std::ops::ControlFlow;

pub const DISALLOWED_FUNCTIONS: &[&str] = &[
    "pg_read_file",
    "pg_read_binary_file",
    "pg_write_file",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_rotate_logfile",
    "pg_reload_conf",
    "lo_export",
    "lo_import",
    "lo_unlink",
    "lo_creat",
    "lo_open",
    "lo_write",
    "dblink",
    "dblink_exec",
    "dblink_connect",
    "load_file",
    "sys_eval",
    "sys_exec",
    "sys_get",
    "sys_set",
    "load_extension",
    "readfile",
    "writefile",
    "benchmark",
    "sleep",
    "pg_sleep",
];

pub const SYSTEM_SCHEMAS: &[&str] = &[
    "pg_catalog",
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
    "sqlite_master",
    "sqlite_schema",
    "sqlite_temp_master",
    "sqlite_temp_schema",
    "sqlite_sequence",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativeSqlValidationResult {
    pub is_valid: bool,
    pub error_message: Option<String>,
    pub extracted_tables: Vec<String>,
    pub normalized_sql: Option<String>,
}

struct SecurityVisitor {
    cte_scopes: Vec<HashSet<String>>,
    extracted_tables: Vec<String>,
}

impl SecurityVisitor {
    fn new() -> Self {
        Self {
            cte_scopes: vec![HashSet::new()],
            extracted_tables: Vec::new(),
        }
    }

    fn is_cte(&self, name: &str) -> bool {
        let lower = name.to_lowercase();
        for scope in self.cte_scopes.iter().rev() {
            if scope.contains(&lower) {
                return true;
            }
        }
        false
    }

    fn push_scope(&mut self) {
        self.cte_scopes.push(HashSet::new());
    }

    fn pop_scope(&mut self) {
        if self.cte_scopes.len() > 1 {
            self.cte_scopes.pop();
        }
    }

    fn add_cte_alias(&mut self, alias: &str) {
        if let Some(scope) = self.cte_scopes.last_mut() {
            scope.insert(alias.to_lowercase());
        }
    }
}

impl Visitor for SecurityVisitor {
    type Break = String;

    fn pre_visit_query(&mut self, query: &Query) -> ControlFlow<Self::Break> {
        self.push_scope();

        // 1. Check with / CTEs
        if let Some(ref with) = query.with {
            for cte in &with.cte_tables {
                let alias = cte.alias.name.value.clone();
                self.add_cte_alias(&alias);

                // Validate CTE query body
                if let Err(msg) = validate_query_body(&cte.query) {
                    return ControlFlow::Break(msg);
                }
            }
        }

        // 2. Validate query body
        if let Err(msg) = validate_query_body(query) {
            return ControlFlow::Break(msg);
        }

        ControlFlow::Continue(())
    }

    fn post_visit_query(&mut self, _query: &Query) -> ControlFlow<Self::Break> {
        self.pop_scope();
        ControlFlow::Continue(())
    }

    fn pre_visit_table_factor(&mut self, table_factor: &TableFactor) -> ControlFlow<Self::Break> {
        if let TableFactor::Table { name, .. } = table_factor {
            let parts: Vec<String> = name.0.iter().map(|p| p.to_string()).collect();
            let full_name = match parts.len() {
                0 => return ControlFlow::Continue(()),
                1 => {
                    let t = &parts[0];
                    if self.is_cte(t) {
                        return ControlFlow::Continue(());
                    }
                    t.clone()
                }
                _ => {
                    // Schema-qualified: never a CTE
                    format!("{}.{}", parts[parts.len() - 2], parts[parts.len() - 1])
                }
            };

            if !self.extracted_tables.contains(&full_name) {
                self.extracted_tables.push(full_name);
            }
        }
        ControlFlow::Continue(())
    }

    fn pre_visit_expr(&mut self, expr: &Expr) -> ControlFlow<Self::Break> {
        if let Expr::Function(func) = expr {
            let func_name = func
                .name
                .0
                .last()
                .map(|p| p.to_string().to_lowercase())
                .unwrap_or_default();

            if DISALLOWED_FUNCTIONS.contains(&func_name.as_str()) {
                return ControlFlow::Break(format!(
                    "Disallowed administrative function '{func_name}' is not permitted."
                ));
            }
        }
        ControlFlow::Continue(())
    }
}

fn validate_query_body(query: &Query) -> Result<(), String> {
    validate_set_expr(&query.body)
}

fn validate_set_expr(expr: &SetExpr) -> Result<(), String> {
    match expr {
        SetExpr::Select(_) => Ok(()),
        SetExpr::Query(q) => validate_query_body(q),
        SetExpr::SetOperation {
            op, left, right, ..
        } => {
            if *op != SetOperator::Union {
                return Err(format!(
                    "Dangerous SQL construct '{op:?}' is strictly forbidden."
                ));
            }
            validate_set_expr(left)?;
            validate_set_expr(right)?;
            Ok(())
        }
        SetExpr::Insert(_) => {
            Err("Dangerous SQL construct 'Insert' is strictly forbidden.".to_string())
        }
        SetExpr::Update(_) => {
            Err("Dangerous SQL construct 'Update' is strictly forbidden.".to_string())
        }
        SetExpr::Delete(_) => {
            Err("Dangerous SQL construct 'Delete' is strictly forbidden.".to_string())
        }
        SetExpr::Values(_) => Ok(()),
        other => Err(format!(
            "Only read-only SELECT queries are permitted (received {other:?})."
        )),
    }
}

pub fn get_dialect(dialect_name: &str) -> Box<dyn Dialect> {
    match dialect_name.trim().to_lowercase().as_str() {
        "postgres" | "postgresql" => Box::new(PostgreSqlDialect {}),
        "mysql" => Box::new(MySqlDialect {}),
        "sqlite" => Box::new(SQLiteDialect {}),
        _ => Box::new(GenericDialect {}),
    }
}

/// Validates that an SQL query complies with single-statement read-only SELECT rules.
pub fn validate_sql_internal(
    query: &str,
    dialect_str: &str,
    allowed_tables: Option<&[String]>,
) -> NativeSqlValidationResult {
    if query.trim().is_empty() {
        return NativeSqlValidationResult {
            is_valid: false,
            error_message: Some("Empty query provided.".to_string()),
            extracted_tables: Vec::new(),
            normalized_sql: None,
        };
    }

    let dialect = get_dialect(dialect_str);
    let statements = match Parser::parse_sql(&*dialect, query) {
        Ok(stmts) => stmts,
        Err(e) => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(format!("SQL syntax error: {e}")),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
    };

    if statements.is_empty() {
        return NativeSqlValidationResult {
            is_valid: false,
            error_message: Some("No valid SQL statements found.".to_string()),
            extracted_tables: Vec::new(),
            normalized_sql: None,
        };
    }

    if statements.len() > 1 {
        return NativeSqlValidationResult {
            is_valid: false,
            error_message: Some(
                "Multi-statement execution is strictly prohibited. Exactly one query is permitted."
                    .to_string(),
            ),
            extracted_tables: Vec::new(),
            normalized_sql: None,
        };
    }

    let stmt = &statements[0];
    let query_ast = match stmt {
        Statement::Query(q) => q,
        Statement::Insert { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Insert' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Update { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Update' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Delete { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Delete' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::CreateTable { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Create' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Drop { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Drop' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::AlterTable { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Alter' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Truncate { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'TruncateTable' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Grant { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Grant' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Revoke { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Revoke' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        Statement::Merge { .. } => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(
                    "Dangerous SQL construct 'Merge' is strictly forbidden.".to_string(),
                ),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
        other => {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(format!(
                    "Only read-only SELECT queries are permitted (received {other:?})."
                )),
                extracted_tables: Vec::new(),
                normalized_sql: None,
            };
        }
    };

    let mut visitor = SecurityVisitor::new();
    if let ControlFlow::Break(err) = query_ast.visit(&mut visitor) {
        return NativeSqlValidationResult {
            is_valid: false,
            error_message: Some(err),
            extracted_tables: visitor.extracted_tables,
            normalized_sql: None,
        };
    }

    let extracted_tables = visitor.extracted_tables;

    // Check system catalog schemas
    for ext_table in &extracted_tables {
        let parts: Vec<&str> = ext_table.split('.').collect();
        let schema_part = if parts.len() > 1 {
            Some(parts[0].to_lowercase())
        } else {
            None
        };
        let bare_table = parts[parts.len() - 1].to_lowercase();

        let is_in_allowlist = if let Some(allowlist) = allowed_tables {
            allowlist
                .iter()
                .any(|a| a.trim().eq_ignore_ascii_case(ext_table))
        } else {
            false
        };

        if let Some(ref s) = schema_part {
            if SYSTEM_SCHEMAS.contains(&s.as_str()) && !is_in_allowlist {
                return NativeSqlValidationResult {
                    is_valid: false,
                    error_message: Some(format!(
                        "Access to protected system schema '{s}' is strictly forbidden."
                    )),
                    extracted_tables,
                    normalized_sql: None,
                };
            }
        }

        if SYSTEM_SCHEMAS.contains(&bare_table.as_str()) && !is_in_allowlist {
            return NativeSqlValidationResult {
                is_valid: false,
                error_message: Some(format!(
                    "Access to protected system catalog '{bare_table}' is strictly forbidden."
                )),
                extracted_tables,
                normalized_sql: None,
            };
        }
    }

    // Check table allowlist if provided
    if let Some(allowlist) = allowed_tables {
        let allowed_with_schema: HashSet<String> = allowlist
            .iter()
            .filter(|t| t.contains('.'))
            .map(|t| t.trim().to_lowercase())
            .collect();

        let allowed_bare: HashSet<String> = allowlist
            .iter()
            .map(|t| {
                let parts: Vec<&str> = t.trim().split('.').collect();
                parts[parts.len() - 1].to_lowercase()
            })
            .collect();

        for ext_table in &extracted_tables {
            let ext_clean = ext_table.to_lowercase();
            let parts: Vec<&str> = ext_clean.split('.').collect();
            let bare_table = parts[parts.len() - 1];

            if parts.len() > 1 {
                let schema_name = parts[0];
                if allowed_with_schema.contains(&ext_clean) {
                    continue;
                }
                if (schema_name == "public" || schema_name == "main")
                    && allowed_bare.contains(bare_table)
                {
                    continue;
                }
                return NativeSqlValidationResult {
                    is_valid: false,
                    error_message: Some(format!(
                        "Unauthorized schema-qualified table reference '{ext_table}'. Allowed tables: {allowlist:?}"
                    )),
                    extracted_tables,
                    normalized_sql: None,
                };
            } else if !allowed_bare.contains(bare_table) {
                return NativeSqlValidationResult {
                    is_valid: false,
                    error_message: Some(format!(
                        "Unauthorized table reference '{ext_table}'. Allowed tables: {allowlist:?}"
                    )),
                    extracted_tables,
                    normalized_sql: None,
                };
            }
        }
    }

    let normalized_sql = query_ast.to_string();

    NativeSqlValidationResult {
        is_valid: true,
        error_message: None,
        extracted_tables,
        normalized_sql: Some(normalized_sql),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_valid_select() {
        let allowed = vec!["customers".to_string(), "orders".to_string()];
        let res = validate_sql_internal(
            "SELECT id, name FROM customers WHERE id = 1;",
            "postgres",
            Some(&allowed),
        );
        assert!(res.is_valid);
        assert_eq!(res.extracted_tables, vec!["customers"]);
    }

    #[test]
    fn test_reject_drop_and_multi_statement() {
        let allowed = vec!["customers".to_string()];
        let res1 = validate_sql_internal("DROP TABLE customers;", "postgres", Some(&allowed));
        assert!(!res1.is_valid);
        assert!(res1.error_message.unwrap().contains("Drop"));

        let res2 = validate_sql_internal(
            "SELECT 1; DROP TABLE customers;",
            "postgres",
            Some(&allowed),
        );
        assert!(!res2.is_valid);
        assert!(res2.error_message.unwrap().contains("Multi-statement"));
    }

    #[test]
    fn test_reject_disallowed_function() {
        let allowed = vec!["customers".to_string()];
        let res = validate_sql_internal(
            "SELECT pg_read_file('/etc/passwd');",
            "postgres",
            Some(&allowed),
        );
        assert!(!res.is_valid);
        assert!(res.error_message.unwrap().contains("pg_read_file"));
    }

    #[test]
    fn test_cte_scope_resolution() {
        let query = "WITH regional_summary AS (SELECT city, count(*) as cnt FROM customers GROUP BY city) SELECT * FROM regional_summary WHERE cnt > 0;";
        let allowed = vec!["customers".to_string()];
        let res = validate_sql_internal(query, "postgres", Some(&allowed));
        assert!(res.is_valid);
        assert_eq!(res.extracted_tables, vec!["customers"]);
    }

    #[test]
    fn test_cte_alias_collision_unauthorized_schema_rejected() {
        let query = "WITH customers AS (SELECT 1 AS id) SELECT * FROM secret_schema.customers;";
        let allowed = vec!["customers".to_string()];
        let res = validate_sql_internal(query, "postgres", Some(&allowed));
        assert!(!res.is_valid);
        assert!(res
            .error_message
            .unwrap()
            .contains("Unauthorized schema-qualified"));
    }

    #[test]
    fn test_cte_with_nested_delete_rejected() {
        let query = "WITH del AS (DELETE FROM orders RETURNING *) SELECT * FROM del;";
        let allowed = vec!["orders".to_string()];
        let res = validate_sql_internal(query, "postgres", Some(&allowed));
        assert!(!res.is_valid);
        assert!(res.error_message.unwrap().contains("Delete"));
    }
}
