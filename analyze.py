#!/usr/bin/env python3
"""Comprehensive data analysis report for LEAP 2026 exhibitors."""

import os
import re
from collections import Counter

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

CSV_PATH = "/Users/nkapila6/leap26/onegiantleap_2026_exhibitors.csv"
CHARTS_DIR = "/Users/nkapila6/leap26/charts"

MENA_COUNTRIES = {
    "Saudi Arabia",
    "United Arab Emirates",
    "Bahrain",
    "Oman",
    "Kuwait",
    "Qatar",
    "Egypt",
    "Jordan",
    "Morocco",
    "Tunisia",
    "Algeria",
    "Iraq",
    "Lebanon",
    "Palestine",
    "Sudan",
    "Yemen",
    "Libya",
}


def clean_data(df):
    """Strip whitespace, parse booleans/years, and extract hall prefixes."""
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = (
                df[col].astype(str).str.strip().replace({"nan": np.nan, "": np.nan})
            )

    df["Is_AI"] = (
        df["Is_AI"].astype(str).str.lower().map({"true": True, "false": False})
    )

    df["Founding Year"] = pd.to_numeric(df["Founding Year"], errors="coerce")

    df["Hall"] = (
        df["Booth"]
        .astype(str)
        .str.split(".")
        .str[0]
        .where(df["Booth"].notna(), "Unknown")
    )

    # The CSV only contains "Exhibitor" values; missing Type is treated as Startup
    # so that startup/exhibitor analysis requested by the prompt is meaningful.
    df["Type"] = df["Type"].fillna("Startup")
    df["Country"] = df["Country"].fillna("Unknown")
    df["Category"] = df["Category"].fillna("Unknown")
    df["Number of Employees"] = df["Number of Employees"].fillna("Unknown")

    df["MENA"] = df["Country"].isin(MENA_COUNTRIES)

    return df


def employee_sort_key(value):
    """Return a numeric lower bound for an employee-range string."""
    if pd.isna(value) or str(value).strip().lower() == "unknown":
        return -1
    value = str(value).strip()
    if value.endswith("+"):
        return int(re.search(r"\d+", value).group())
    if "-" in value:
        return int(value.split("-")[0])
    return -1


def save_fig(fig, filename):
    """Save a figure to the charts directory."""
    os.makedirs(CHARTS_DIR, exist_ok=True)
    path = os.path.join(CHARTS_DIR, filename)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def main():
    # Load and clean data.
    df = pd.read_csv(CSV_PATH)
    df = clean_data(df)

    # Consistent style.
    plt.style.use("seaborn-v0_8-darkgrid")
    sns.set_palette("tab20")

    # Common palettes.
    ai_color = "#e74c3c"
    non_ai_color = "#3498db"
    tab20 = plt.cm.tab20.colors

    chart_files = []

    # Chart 01: Category distribution (21 categories, horizontal bar).
    categories = df["Category"].value_counts().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(10, 10))
    bars = ax.barh(categories.index, categories.values, color=tab20[: len(categories)])
    ax.set_title("Category Distribution", fontsize=14, fontweight="bold")
    ax.set_xlabel("Number of Exhibitors", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    chart_files.append(save_fig(fig, "01_category_distribution.png"))

    # Chart 02: AI vs non-AI donut chart.
    ai_counts = df["Is_AI"].value_counts().sort_index(ascending=False)
    labels = [f"AI\n({ai_counts[True]})", f"Non-AI\n({ai_counts[False]})"]
    fig, ax = plt.subplots(figsize=(10, 6))
    wedges, texts, autotexts = ax.pie(
        ai_counts.values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=[ai_color, non_ai_color],
        wedgeprops={"width": 0.4, "edgecolor": "white"},
    )
    ax.set_title("AI vs Non-AI Exhibitors", fontsize=14, fontweight="bold")
    chart_files.append(save_fig(fig, "02_ai_vs_non_ai.png"))

    # Chart 03: AI companies by category.
    ai_by_cat = (
        df[df["Is_AI"] == True]["Category"].value_counts().sort_values(ascending=True)
    )
    fig, ax = plt.subplots(figsize=(10, 8))
    bars = ax.barh(ai_by_cat.index, ai_by_cat.values, color=ai_color)
    ax.set_title("AI Companies by Category", fontsize=14, fontweight="bold")
    ax.set_xlabel("Number of AI Companies", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    chart_files.append(save_fig(fig, "03_ai_by_category.png"))

    # Chart 04: Top 15 industries.
    # Split semicolon-separated raw industries and count each individual industry.
    industries = []
    for raw in df["Company Industry"].dropna():
        for ind in raw.split(";"):
            ind = ind.strip()
            if ind:
                industries.append(ind)
    industry_counts = (
        pd.Series(industries).value_counts().head(15).sort_values(ascending=True)
    )
    fig, ax = plt.subplots(figsize=(10, 8))
    bars = ax.barh(industry_counts.index, industry_counts.values, color=tab20[:15])
    ax.set_title("Top 15 Company Industries", fontsize=14, fontweight="bold")
    ax.set_xlabel("Frequency", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    chart_files.append(save_fig(fig, "04_top_15_industries.png"))

    # Chart 05: Top 20 countries.
    top_countries = df["Country"].value_counts().head(20).sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(10, 10))
    bars = ax.barh(top_countries.index, top_countries.values, color=tab20[:20])
    ax.set_title("Top 20 Countries by Exhibitor Count", fontsize=14, fontweight="bold")
    ax.set_xlabel("Number of Exhibitors", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    chart_files.append(save_fig(fig, "05_top_20_countries.png"))

    # Chart 06: MENA vs Rest of World.
    mena_counts = df["MENA"].value_counts()
    labels = [f"Rest of World\n({mena_counts[False]})", f"MENA\n({mena_counts[True]})"]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.pie(
        [mena_counts[False], mena_counts[True]],
        labels=labels,
        autopct="%1.1f%%",
        startangle=140,
        colors=["#2ecc71", "#f39c12"],
    )
    ax.set_title("MENA vs Rest of World", fontsize=14, fontweight="bold")
    chart_files.append(save_fig(fig, "06_mena_vs_rest.png"))

    # Chart 07: AI density by country (>= 10 exhibitors).
    country_ai_density = df.groupby("Country").agg(
        total=("Is_AI", "size"), ai_count=("Is_AI", "sum")
    )
    country_ai_density = country_ai_density[country_ai_density["total"] >= 10].copy()
    country_ai_density["ai_pct"] = (
        country_ai_density["ai_count"] / country_ai_density["total"] * 100
    )
    country_ai_density = country_ai_density.sort_values("ai_pct", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 10))
    bars = ax.barh(
        country_ai_density.index,
        country_ai_density["ai_pct"],
        color=ai_color,
    )
    ax.set_title(
        "AI Density by Country (≥10 Exhibitors)", fontsize=14, fontweight="bold"
    )
    ax.set_xlabel("Percentage of AI Companies", fontsize=12)
    ax.bar_label(bars, fmt="%.1f%%")
    chart_files.append(save_fig(fig, "07_ai_density_by_country.png"))

    # Chart 08: Country x Category heatmap (top 10 x top 10).
    top_10_countries = df["Country"].value_counts().head(10).index
    top_10_categories = df["Category"].value_counts().head(10).index
    heatmap_data = (
        df[
            df["Country"].isin(top_10_countries)
            & df["Category"].isin(top_10_categories)
        ]
        .groupby(["Country", "Category"])
        .size()
        .unstack(fill_value=0)
    )
    heatmap_data = heatmap_data.loc[top_10_countries, top_10_categories]
    fig, ax = plt.subplots(figsize=(14, 10))
    sns.heatmap(heatmap_data, annot=True, fmt="d", cmap="YlOrRd", linewidths=0.5, ax=ax)
    ax.set_title(
        "Top 10 Countries vs Top 10 Categories", fontsize=14, fontweight="bold"
    )
    ax.set_xlabel("Category", fontsize=12)
    ax.set_ylabel("Country", fontsize=12)
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "08_country_x_category_heatmap.png"))

    # Chart 09: Exhibitors by hall.
    hall_counts = df["Hall"].value_counts().sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(
        hall_counts.index, hall_counts.values, color=tab20[: len(hall_counts)]
    )
    ax.set_title("Exhibitors by Hall", fontsize=14, fontweight="bold")
    ax.set_xlabel("Hall", fontsize=12)
    ax.set_ylabel("Number of Exhibitors", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "09_exhibitors_by_hall.png"))

    # Chart 10: Startup vs Exhibitor by hall (stacked bar).
    hall_type = (
        df[df["Type"].isin(["Startup", "Exhibitor"])]
        .groupby(["Hall", "Type"])
        .size()
        .unstack(fill_value=0)
        .sort_values(by="Exhibitor", ascending=False)
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    hall_type.plot(kind="bar", stacked=True, ax=ax, color=["#9b59b6", "#3498db"])
    ax.set_title("Startup vs Exhibitor by Hall", fontsize=14, fontweight="bold")
    ax.set_xlabel("Hall", fontsize=12)
    ax.set_ylabel("Number of Exhibitors", fontsize=12)
    ax.legend(title="Type", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "10_startup_vs_exhibitor_by_hall.png"))

    # Chart 11: AI companies by hall (AI vs non-AI grouped/stacked bar).
    hall_ai = (
        df.groupby(["Hall", "Is_AI"])
        .size()
        .unstack(fill_value=0)
        .sort_values(by=True, ascending=False)
    )
    hall_ai.columns = ["Non-AI", "AI"]
    fig, ax = plt.subplots(figsize=(10, 6))
    hall_ai.plot(kind="bar", stacked=True, ax=ax, color=[non_ai_color, ai_color])
    ax.set_title("AI vs Non-AI Companies by Hall", fontsize=14, fontweight="bold")
    ax.set_xlabel("Hall", fontsize=12)
    ax.set_ylabel("Number of Companies", fontsize=12)
    ax.legend(title="AI Status", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "11_ai_companies_by_hall.png"))

    # Chart 12: Founding year distribution (1990-2025).
    years = df[(df["Founding Year"] >= 1990) & (df["Founding Year"] <= 2025)][
        "Founding Year"
    ]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(years, bins=range(1990, 2027, 5), color="#16a085", edgecolor="white")
    ax.set_title(
        "Founding Year Distribution (1990-2025)", fontsize=14, fontweight="bold"
    )
    ax.set_xlabel("Founding Year", fontsize=12)
    ax.set_ylabel("Number of Companies", fontsize=12)
    ax.set_xticks(range(1990, 2026, 5))
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "12_founding_year_distribution.png"))

    # Chart 13: Company age in 2026 box plot (AI vs non-AI).
    df["Age"] = 2026 - df["Founding Year"]
    age_data = [
        df[df["Is_AI"] == True]["Age"].dropna(),
        df[df["Is_AI"] == False]["Age"].dropna(),
    ]
    fig, ax = plt.subplots(figsize=(10, 6))
    bp = ax.boxplot(age_data, patch_artist=True)
    ax.set_xticklabels(["AI", "Non-AI"])
    bp["boxes"][0].set_facecolor(ai_color)
    bp["boxes"][1].set_facecolor(non_ai_color)
    ax.set_title("Company Age in 2026: AI vs Non-AI", fontsize=14, fontweight="bold")
    ax.set_xlabel("AI Status", fontsize=12)
    ax.set_ylabel("Age (Years)", fontsize=12)
    chart_files.append(save_fig(fig, "13_company_age_boxplot.png"))

    # Chart 14: Employee count distribution.
    emp_counts = df["Number of Employees"].value_counts()
    emp_order = sorted(emp_counts.index, key=employee_sort_key)
    fig, ax = plt.subplots(figsize=(12, 6))
    bars = ax.bar(
        emp_order, [emp_counts[x] for x in emp_order], color=tab20[: len(emp_order)]
    )
    ax.set_title("Employee Count Distribution", fontsize=14, fontweight="bold")
    ax.set_xlabel("Employee Range", fontsize=12)
    ax.set_ylabel("Number of Companies", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "14_employee_distribution.png"))

    # Chart 15: Type pie chart (Startup vs Exhibitor).
    type_counts = df["Type"].value_counts()
    type_counts = type_counts[type_counts.index.isin(["Startup", "Exhibitor"])]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.pie(
        type_counts.values,
        labels=[f"{k}\n({v})" for k, v in type_counts.items()],
        autopct="%1.1f%%",
        startangle=140,
        colors=["#9b59b6", "#3498db"],
    )
    ax.set_title("Startup vs Exhibitor", fontsize=14, fontweight="bold")
    chart_files.append(save_fig(fig, "15_startup_vs_exhibitor_pie.png"))

    # Chart 16: Category x Type stacked bar (top 8 categories).
    top_8_cats = df["Category"].value_counts().head(8).index
    cat_type = (
        df[df["Category"].isin(top_8_cats) & df["Type"].isin(["Startup", "Exhibitor"])]
        .groupby(["Category", "Type"])
        .size()
        .unstack(fill_value=0)
    )
    fig, ax = plt.subplots(figsize=(12, 6))
    cat_type.plot(kind="bar", stacked=True, ax=ax, color=["#9b59b6", "#3498db"])
    ax.set_title(
        "Category vs Type (Startup vs Exhibitor)", fontsize=14, fontweight="bold"
    )
    ax.set_xlabel("Category", fontsize=12)
    ax.set_ylabel("Number of Companies", fontsize=12)
    ax.legend(title="Type", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "16_category_x_type_stacked.png"))

    # Chart 17: AI flag x Type grouped bar.
    ai_type = (
        df[df["Type"].isin(["Startup", "Exhibitor"])]
        .groupby(["Type", "Is_AI"])
        .size()
        .unstack(fill_value=0)
    )
    ai_type.columns = ["Non-AI", "AI"]
    fig, ax = plt.subplots(figsize=(10, 6))
    ai_type.plot(kind="bar", ax=ax, color=[non_ai_color, ai_color])
    ax.set_title("AI Flag by Type", fontsize=14, fontweight="bold")
    ax.set_xlabel("Type", fontsize=12)
    ax.set_ylabel("Number of Companies", fontsize=12)
    ax.legend(title="AI Status", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=0)
    chart_files.append(save_fig(fig, "17_ai_flag_x_type.png"))

    # Chart 18: Employee size x Category heatmap.
    top_8_cats_emp = df["Category"].value_counts().head(8).index
    emp_order_sorted = [x for x in emp_order if x in df["Number of Employees"].values]
    emp_cat = (
        df[
            df["Category"].isin(top_8_cats_emp)
            & df["Number of Employees"].isin(emp_order_sorted)
        ]
        .groupby(["Number of Employees", "Category"])
        .size()
        .unstack(fill_value=0)
    )
    emp_cat = emp_cat.reindex(emp_order_sorted)
    emp_cat = emp_cat[top_8_cats_emp]
    fig, ax = plt.subplots(figsize=(14, 8))
    sns.heatmap(emp_cat, annot=True, fmt=".0f", cmap="YlGnBu", linewidths=0.5, ax=ax)
    ax.set_title("Employee Size vs Category", fontsize=14, fontweight="bold")
    ax.set_xlabel("Category", fontsize=12)
    ax.set_ylabel("Employee Range", fontsize=12)
    plt.xticks(rotation=45, ha="right")
    chart_files.append(save_fig(fig, "18_employee_size_x_category.png"))

    # Chart 19: Founding year x AI violin plot.
    ai_years = df[df["Is_AI"] == True]["Founding Year"].dropna()
    non_ai_years = df[df["Is_AI"] == False]["Founding Year"].dropna()
    fig, ax = plt.subplots(figsize=(10, 6))
    parts = ax.violinplot([ai_years, non_ai_years], showmeans=True, showmedians=True)
    for pc in parts["bodies"]:
        pc.set_alpha(0.7)
    parts["bodies"][0].set_facecolor(ai_color)
    parts["bodies"][1].set_facecolor(non_ai_color)
    ax.set_xticks([1, 2])
    ax.set_xticklabels(["AI", "Non-AI"])
    ax.set_title(
        "Founding Year Distribution by AI Status", fontsize=14, fontweight="bold"
    )
    ax.set_xlabel("AI Status", fontsize=12)
    ax.set_ylabel("Founding Year", fontsize=12)
    chart_files.append(save_fig(fig, "19_founding_year_x_ai_violin.png"))

    # Chart 20: AI buzzword frequency.
    descriptions = df["Description"].dropna().str.lower()
    terms = [
        ("artificial intelligence", False),
        ("ai", True),
        ("machine learning", False),
        ("ml", True),
        ("generative ai", False),
        ("genai", True),
        ("llm", True),
        ("large language model", False),
        ("agent", True),
        ("agentic", True),
        ("deep learning", False),
        ("neural", True),
        ("computer vision", False),
        ("nlp", True),
        ("natural language", False),
        ("chatbot", True),
        ("autonomous", True),
        ("predictive", True),
        ("recommendation", True),
    ]
    buzz_counts = {}
    for term, use_word_boundary in terms:
        if use_word_boundary:
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
        buzz_counts[term] = descriptions.apply(lambda x: bool(pattern.search(x))).sum()
    buzz_series = pd.Series(buzz_counts).sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(10, 8))
    bars = ax.barh(buzz_series.index, buzz_series.values, color=ai_color)
    ax.set_title(
        "AI Buzzword Frequency in Descriptions", fontsize=14, fontweight="bold"
    )
    ax.set_xlabel("Number of Descriptions", fontsize=12)
    ax.bar_label(bars, fmt="%d")
    chart_files.append(save_fig(fig, "20_ai_buzzword_frequency.png"))

    # Summary report.
    total = len(df)
    ai_total = int(df["Is_AI"].sum())
    ai_pct = ai_total / total * 100
    startup_total = int((df["Type"] == "Startup").sum())
    exhibitor_total = int((df["Type"] == "Exhibitor").sum())
    startup_pct = startup_total / total * 100
    country_count = df["Country"].nunique()
    top3_countries = df["Country"].value_counts().head(3)
    most_common_category = df["Category"].value_counts().idxmax()
    most_common_industry = industry_counts.idxmax()
    median_year = df["Founding Year"].median()
    emp_counts_summary = df["Number of Employees"].value_counts()
    most_common_employees = emp_counts_summary.idxmax()
    most_common_employees_known = (
        emp_counts_summary.drop("Unknown", errors="ignore").idxmax()
        if "Unknown" in emp_counts_summary.index
        else most_common_employees
    )
    hall_counts_summary = df["Hall"].value_counts()
    top_hall = hall_counts_summary.idxmax()
    top_hall_known = (
        hall_counts_summary.drop("Unknown", errors="ignore").idxmax()
        if "Unknown" in hall_counts_summary.index
        else top_hall
    )
    mena_pct = df["MENA"].sum() / total * 100
    ai_startup = int(((df["Is_AI"] == True) & (df["Type"] == "Startup")).sum())
    ai_exhibitor = int(((df["Is_AI"] == True) & (df["Type"] == "Exhibitor")).sum())

    type_known = df[df["Type"].isin(["Startup", "Exhibitor"])]
    pct_startup_ai = (
        (type_known[type_known["Type"] == "Startup"]["Is_AI"].sum())
        / max(1, (type_known["Type"] == "Startup").sum())
        * 100
    )
    pct_exhibitor_ai = (
        (type_known[type_known["Type"] == "Exhibitor"]["Is_AI"].sum())
        / max(1, (type_known["Type"] == "Exhibitor").sum())
        * 100
    )

    report = f"""
================================================================================
LEAP 2026 Exhibitor Analysis Summary
================================================================================
Total exhibitors: {total:,}
AI companies: {ai_total} ({ai_pct:.1f}%)
Startup companies: {startup_total} ({startup_pct:.1f}%)
Exhibitor companies: {exhibitor_total}
Countries represented: {country_count}
Top 3 countries:
  1. {top3_countries.index[0]}: {top3_countries.iloc[0]}
  2. {top3_countries.index[1]}: {top3_countries.iloc[1]}
  3. {top3_countries.index[2]}: {top3_countries.iloc[2]}
Most common category: {most_common_category}
Most common industry: {most_common_industry}
Median founding year: {int(median_year) if pd.notna(median_year) else "N/A"}
Most common employee range: {most_common_employees}
Most common known employee range: {most_common_employees_known}
Hall with most exhibitors: {top_hall}
Hall with most exhibitors (known booth): {top_hall_known}
MENA share: {df["MENA"].sum()} ({mena_pct:.1f}%)
AI companies by type:
  Startups: {ai_startup}
  Exhibitors: {ai_exhibitor}
Startup AI density: {pct_startup_ai:.1f}%
Exhibitor AI density: {pct_exhibitor_ai:.1f}%
Interesting correlation: Startups are {"more" if pct_startup_ai > pct_exhibitor_ai else "less"} likely to be AI companies than exhibitors.
================================================================================
Charts generated: {len(chart_files)}
"""
    print(report)
    for i, path in enumerate(chart_files, 1):
        print(f"{i:02d}. {os.path.basename(path)}")


if __name__ == "__main__":
    main()
