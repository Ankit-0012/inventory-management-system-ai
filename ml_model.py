import sqlite3
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor


def predict_sales(product_id):

    conn = sqlite3.connect("inventory.db")

    df = pd.read_sql_query("""
    SELECT sale_date, SUM(quantity_sold) as total_sales
    FROM sales
    WHERE product_id=?
    GROUP BY sale_date
    ORDER BY sale_date
    """, conn, params=(product_id,))

    conn.close()

    # NO DATA
    if len(df) == 0:
        return {
            "daily": 0,
            "weekly": 0,
            "monthly": 0,
            "forecast": [0]*30
        }

    sales = df["total_sales"].tolist()

    # VERY SMALL DATA
    if len(sales) < 5:

        avg = int(np.mean(sales))

        forecast = []

        last = avg

        for i in range(30):

            fluctuation = np.random.randint(-3,4)

            val = last + fluctuation

            if val < 0:
                val = avg

            forecast.append(val)

            last = val

        return {
            "daily": avg,
            "weekly": avg*7,
            "monthly": avg*30,
            "forecast": forecast
        }

    # CREATE DAY INDEX
    df["day"] = range(len(df))

    X = df[["day"]]
    y = df["total_sales"]

    model = RandomForestRegressor(
        n_estimators=300,
        random_state=42
    )

    model.fit(X, y)

    # NEXT DAY PREDICTION
    next_day = pd.DataFrame([[len(df)]], columns=["day"])

    daily = int(model.predict(next_day)[0])

    if daily < 0:
        daily = int(np.mean(sales))

    # FUTURE DAYS
    future_days = pd.DataFrame(
        np.arange(len(df), len(df)+30),
        columns=["day"]
    )

    predictions = model.predict(future_days)

    forecast = []

    last_value = int(predictions[0])

    for p in predictions:

        val = int(p)

        # ADD RANDOM FLUCTUATION (ZIGZAG EFFECT)
        fluctuation = np.random.randint(-4,5)

        val = val + fluctuation

        if val < 0:
            val = last_value

        forecast.append(val)

        last_value = val

    return {
        "daily": daily,
        "weekly": daily*7,
        "monthly": daily*30,
        "forecast": forecast
    }