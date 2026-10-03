// =====================================================================================
// Power Query (M) for the Vittora Credit report.  SYNTHETIC DATA.
// 1. Create a text parameter  DataFolder  = full path to powerbi\data\ (with trailing backslash).
// 2. Create a blank query named fnLoadCsv and paste the function below.
// 3. For each table create a blank query with one line, e.g.   = fnLoadCsv("fct_loans")
//    (query names must equal the CSV names so the DAX in powerbi/dax/measures.dax resolves).
// Typing rules: *_id/label columns -> text; *_date / *_day / month_start / week_start / cohort_month ->
// date; *_ts -> datetime; is_*/has_*/known booleans -> logical; everything else becomes a number
// when every sampled value parses as one, otherwise text.
// =====================================================================================

// ---------- fnLoadCsv ----------
(fileName as text) as table =>
let
    Source = Csv.Document(
        File.Contents(DataFolder & fileName & ".csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Cols = Table.ColumnNames(Promoted),
    BoolCols = {"autopay_enabled", "significant", "detected", "kyc_completed_7d", "app_submitted_14d", "disbursed_30d",
                "fpd30_mature", "ever_30dpd", "ever_90dpd", "fully_mature", "marketing_opt_in", "is_weekend",
                "reached_kyc_started", "reached_kyc_completed", "reached_app_started", "reached_app_submitted",
                "reached_approved", "reached_disbursed", "is_mature_7d", "is_mature_30d", "is_paid", "is_secured", "is_active"},
    DateCols = {"month_start", "week_start", "quarter_start", "cohort_month", "disbursal_month", "vintage_quarter",
                "signup_quarter", "activity_month", "start_date", "end_date", "launch_date", "maturity_date",
                "closed_date", "first_due_date", "first_30dpd_date", "write_off_date", "date_day", "revenue_date"},
    TypeFor = (c as text) as nullable type =>
        if List.Contains(BoolCols, c) or Text.StartsWith(c, "is_") or Text.StartsWith(c, "has_") then type logical
        else if List.Contains(DateCols, c) or Text.EndsWith(c, "_date") then type date
        else if Text.EndsWith(c, "_ts") then type datetime
        else if Text.EndsWith(c, "_id") or Text.EndsWith(c, "_name") or Text.EndsWith(c, "_label") then type text
        else null,
    Explicit = List.Select(List.Transform(Cols, each {_, TypeFor(_)}), each _{1} <> null),
    Remaining = List.Difference(Cols, List.Transform(Explicit, each _{0})),
    Sample = Table.FirstN(Promoted, 500),
    IsNumeric = (c as text) as logical =>
        let
            Values = List.Select(Table.Column(Sample, c), each _ <> null and _ <> ""),
            Parsed = List.Transform(Values, each try Number.FromText(_, "en-US") otherwise null)
        in
            List.Count(Values) > 0 and List.NonNullCount(Parsed) = List.Count(Values),
    Numeric = List.Transform(List.Select(Remaining, IsNumeric), each {_, type number}),
    Texts = List.Transform(List.Difference(Remaining, List.Transform(Numeric, each _{0})), each {_, type text}),
    Typed = Table.TransformColumnTypes(Promoted, Explicit & Numeric & Texts, "en-US")
in
    Typed

// ---------- example table queries ----------
// dim_date            = fnLoadCsv("dim_date")
// fct_loans           = fnLoadCsv("fct_loans")
// fct_revenue         = fnLoadCsv("fct_revenue")
// fct_kpi_monthly     = fnLoadCsv("fct_kpi_monthly")
// ... one per CSV in powerbi/data (see powerbi/model/data_model.md for the list)

// ---------- disconnected table for the funnel visual ('Funnel Stage') ----------
// = #table({"Stage Order", "Stage"},
//     {{1, "Signed up"}, {2, "KYC started"}, {3, "KYC completed"}, {4, "Application started"},
//      {5, "Application submitted"}, {6, "Approved"}, {7, "Disbursed"}})
