//! High-performance Columnar Statistical Profiler & Sensitive PII Scanner.

use rayon::prelude::*;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::LazyLock;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct NumericColumnStats {
    pub min_value: Option<f64>,
    pub max_value: Option<f64>,
    pub mean_value: Option<f64>,
    pub median_value: Option<f64>,
    pub std_value: Option<f64>,
    pub q25: Option<f64>,
    pub q75: Option<f64>,
    pub iqr: Option<f64>,
    pub outlier_count: usize,
    pub outlier_ratio: f64,
}

static PII_REGEXES: LazyLock<Vec<(&'static str, Regex)>> = LazyLock::new(|| {
    vec![
        (
            "EMAIL",
            Regex::new(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$").unwrap(),
        ),
        (
            "PHONE",
            Regex::new(r"^(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}$")
                .unwrap(),
        ),
        (
            "CREDIT_CARD",
            Regex::new(r"^(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})$").unwrap(),
        ),
        ("SSN", Regex::new(r"^\d{3}-\d{2}-\d{4}$").unwrap()),
        (
            "IP_ADDRESS",
            Regex::new(
                r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$",
            )
            .unwrap(),
        ),
    ]
});

/// Computes comprehensive statistical metrics and IQR outliers for numeric values.
pub fn compute_numeric_stats_internal(values: &[f64]) -> NumericColumnStats {
    let mut valid_nums: Vec<f64> = values
        .iter()
        .copied()
        .filter(|v| !v.is_nan() && !v.is_infinite())
        .collect();

    let count = valid_nums.len();
    if count == 0 {
        return NumericColumnStats {
            min_value: None,
            max_value: None,
            mean_value: None,
            median_value: None,
            std_value: None,
            q25: None,
            q75: None,
            iqr: None,
            outlier_count: 0,
            outlier_ratio: 0.0,
        };
    }

    // Min and Max
    let (min_v, max_v) = valid_nums
        .par_iter()
        .copied()
        .fold(
            || (f64::INFINITY, f64::NEG_INFINITY),
            |(min, max), v| (min.min(v), max.max(v)),
        )
        .reduce(
            || (f64::INFINITY, f64::NEG_INFINITY),
            |(min1, max1), (min2, max2)| (min1.min(min2), max1.max(max2)),
        );

    // Mean
    let sum: f64 = valid_nums.par_iter().sum();
    let mean_v = sum / (count as f64);

    // Sample Standard Deviation (two-pass)
    let variance_sum: f64 = valid_nums
        .par_iter()
        .map(|v| {
            let diff = v - mean_v;
            diff * diff
        })
        .sum();

    let std_v = if count > 1 {
        (variance_sum / ((count - 1) as f64)).sqrt()
    } else {
        0.0
    };

    // Sort valid numbers to calculate exact quantiles and median
    valid_nums.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let median_v = calculate_percentile(&valid_nums, 0.50);
    let q25 = calculate_percentile(&valid_nums, 0.25);
    let q75 = calculate_percentile(&valid_nums, 0.75);
    let iqr = q75 - q25;

    let mut outlier_count = 0;
    if iqr > 0.0 {
        let lower_bound = q25 - (1.5 * iqr);
        let upper_bound = q75 + (1.5 * iqr);
        outlier_count = valid_nums
            .par_iter()
            .filter(|&&v| v < lower_bound || v > upper_bound)
            .count();
    }

    let outlier_ratio = (outlier_count as f64) / (count as f64);

    NumericColumnStats {
        min_value: Some(round3(min_v)),
        max_value: Some(round3(max_v)),
        mean_value: Some(round3(mean_v)),
        median_value: Some(round3(median_v)),
        std_value: Some(round3(std_v)),
        q25: Some(round3(q25)),
        q75: Some(round3(q75)),
        iqr: Some(round3(iqr)),
        outlier_count,
        outlier_ratio: round3(outlier_ratio),
    }
}

/// Helper calculating linear percentile matching pandas/numpy linear method.
fn calculate_percentile(sorted_data: &[f64], p: f64) -> f64 {
    let n = sorted_data.len();
    if n == 0 {
        return 0.0;
    }
    if n == 1 {
        return sorted_data[0];
    }
    let rank = p * ((n - 1) as f64);
    let low = rank.floor() as usize;
    let high = rank.ceil() as usize;
    let weight = rank - (low as f64);

    if low == high {
        sorted_data[low]
    } else {
        sorted_data[low] + weight * (sorted_data[high] - sorted_data[low])
    }
}

fn round3(val: f64) -> f64 {
    (val * 1000.0).round() / 1000.0
}

/// Scans sample string values to detect sensitive PII entities (email, phone, credit card, SSN, IP).
pub fn detect_pii_internal(samples: &[String]) -> (Option<String>, f64) {
    if samples.is_empty() {
        return (None, 0.0);
    }

    let clean_samples: Vec<&str> = samples
        .iter()
        .map(|s| s.trim())
        .filter(|s| {
            !s.is_empty()
                && !s.eq_ignore_ascii_case("none")
                && !s.eq_ignore_ascii_case("nan")
                && !s.eq_ignore_ascii_case("null")
        })
        .take(100)
        .collect();

    if clean_samples.is_empty() {
        return (None, 0.0);
    }

    let total = clean_samples.len();
    for (pii_type, regex) in PII_REGEXES.iter() {
        let matches = clean_samples.iter().filter(|s| regex.is_match(s)).count();
        let ratio = (matches as f64) / (total as f64);
        if ratio >= 0.40 {
            return (
                Some((*pii_type).to_string()),
                (ratio * 100.0).round() / 100.0,
            );
        }
    }

    (None, 0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_numeric_stats_and_iqr() {
        let mut data = vec![10.0, 12.0, 14.0, 15.0, 16.0, 18.0, 20.0, 22.0];
        // Add an extreme outlier
        data.push(1000.0);

        let stats = compute_numeric_stats_internal(&data);
        assert_eq!(stats.min_value, Some(10.0));
        assert_eq!(stats.max_value, Some(1000.0));
        assert_eq!(stats.outlier_count, 1);
        assert!(stats.outlier_ratio > 0.0);
    }

    #[test]
    fn test_pii_scanner() {
        let emails: Vec<String> = (0..50)
            .map(|i| format!("user_{}@enterprise.com", i))
            .collect();
        let (pii_type, ratio) = detect_pii_internal(&emails);
        assert_eq!(pii_type, Some("EMAIL".to_string()));
        assert_eq!(ratio, 1.0);

        let safe: Vec<String> = vec!["Retail".to_string(), "Wholesale".to_string()];
        let (none_type, _) = detect_pii_internal(&safe);
        assert_eq!(none_type, None);
    }
}
