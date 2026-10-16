
DROP TABLE IF EXISTS "${OUTPUT_SOURCE}"."tpcds-1tb".catalog_sales;
CREATE TABLE "${OUTPUT_SOURCE}"."tpcds-1tb".catalog_sales
STORE AS (type => 'iceberg')
AS SELECT * FROM "${INPUT_SOURCE}".STACKIT_S3."tpcds-1tb-flat".catalog_sales;

