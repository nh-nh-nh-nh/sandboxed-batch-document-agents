# Sample CSV files

Ten simple, well-formed CSV files for ad-hoc testing (upload flows, parsing,
manual exploration). Each has a header row and 10 data rows, all valid UTF-8
with no edge cases.

- `employees.csv` — employee roster
- `products.csv` — product catalog
- `orders.csv` — customer orders
- `students.csv` — student grades
- `weather.csv` — daily weather readings
- `books.csv` — book catalog
- `expenses.csv` — personal expenses
- `inventory_counts.csv` — warehouse inventory
- `website_visits.csv` — page analytics
- `employee_survey.csv` — employee satisfaction survey

Two larger files (100k rows each, several MB) for testing performance and
batch handling on bigger inputs:

- `large_transactions.csv` — financial transactions
- `large_sensor_readings.csv` — IoT sensor readings

For the edge-case corpus (messy data, injection attempts, encoding issues,
etc.) used by the analysis pipeline's tests, see `fixtures/generate.py`
instead.
