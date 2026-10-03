-- Calendar dimension (one row per day in the reporting window). Indian fiscal year runs April-March.
CREATE OR REPLACE TABLE marts.dim_date AS
SELECT
    CAST(t.d AS DATE)                                          AS date_day,
    CAST(date_trunc('week', t.d) AS DATE)                      AS week_start,      -- ISO week, Monday start
    CAST(date_trunc('month', t.d) AS DATE)                     AS month_start,
    CAST(date_trunc('quarter', t.d) AS DATE)                   AS quarter_start,
    CAST(EXTRACT(year FROM t.d) AS INTEGER)                    AS calendar_year,
    CAST(EXTRACT(month FROM t.d) AS INTEGER)                   AS month_num,
    strftime(t.d, '%b %Y')                                     AS month_label,
    CAST(EXTRACT(isodow FROM t.d) AS INTEGER)                  AS iso_dow,
    dayname(t.d)                                               AS day_name,
    EXTRACT(isodow FROM t.d) IN (6, 7)                         AS is_weekend,
    'FY' || CAST(CASE WHEN EXTRACT(month FROM t.d) >= 4
                      THEN EXTRACT(year FROM t.d) + 1
                      ELSE EXTRACT(year FROM t.d) END AS INTEGER) AS fiscal_year
FROM marts.run_params p,
     range(CAST(p.start_date AS TIMESTAMP), CAST(p.as_of_date AS TIMESTAMP) + INTERVAL 1 DAY, INTERVAL 1 DAY) AS t(d);
