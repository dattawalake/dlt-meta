"""Tests for Dataflowpipeline."""
from datetime import datetime
import json
import sys
import tempfile
from pyspark.sql.functions import lit
from tests.utils import DLTFrameworkTestCase
from unittest.mock import MagicMock, patch
from src.dataflow_spec import BronzeDataflowSpec, SilverDataflowSpec
sys.modules["dlt"] = MagicMock()
from src.dataflow_pipeline import DataflowPipeline
from src.onboard_dataflowspec import OnboardDataflowspec
from src.dataflow_spec import DataflowSpecUtils
from src.pipeline_readers import PipelineReaders

dlt = MagicMock()
dlt.expect_all_or_drop = MagicMock()
raw_delta_table_stream = MagicMock()


class DataflowPipelineTests(DLTFrameworkTestCase):
    """Test for Dataflowpipeline."""

    bronze_dataflow_spec_map = {
        "dataFlowId": "1",
        "dataFlowGroup": "A1",
        "sourceFormat": "json",
        "sourceDetails": {"path": "tests/resources/data/customers"},
        "readerConfigOptions": {
        },
        "targetFormat": "delta",
        "targetDetails": {"database": "bronze", "table": "customer", "path": "tests/resources/delta/customers"},
        "tableProperties": {},
        "schema": None,
        "partitionColumns": [""],
        "cdcApplyChanges": None,
        "dataQualityExpectations": """{
            "expect_or_drop": {
                "no_rescued_data": "_rescued_data IS NULL",
                "valid_id": "id IS NOT NULL",
                "valid_operation": "operation IN ('APPEND', 'DELETE', 'UPDATE')"
            }
        }""",
        "quarantineTargetDetails": {
            "database": "bronze", "table": "customer_dqe", "path": "tests/localtest/delta/customers_dqe"
        },
        "quarantineTableProperties": {},
        "version": "v1",
        "createDate": datetime.now,
        "createdBy": "dlt-meta-unittest",
        "updateDate": datetime.now,
        "updatedBy": "dlt-meta-unittest",
    }
    silver_cdc_apply_changes = {
        "keys": ["id"],
        "sequence_by": "operation_date",
        "scd_type": "1",
        "apply_as_deletes": "operation = 'DELETE'",
        "except_column_list": ["operation", "operation_date", "_rescued_data"],
    }
    silver_cdc_apply_changes_scd2 = {
        "keys": ["id"],
        "sequence_by": "operation_date",
        "scd_type": "2",
        "apply_as_deletes": "operation = 'DELETE'",
        "except_column_list": ["operation", "operation_date", "_rescued_data"],
    }
    silver_dataflow_spec_map = {
        "dataFlowId": "1",
        "dataFlowGroup": "A1",
        "sourceFormat": "delta",
        "sourceDetails": {
            "database": "bronze",
            "table": "customer",
            "path": bronze_dataflow_spec_map["targetDetails"]["path"],
        },
        "readerConfigOptions": {},
        "targetFormat": "delta",
        "targetDetails": {"database": "silver", "table": "customer", "path": tempfile.mkdtemp()},
        "tableProperties": {},
        "selectExp": [
            "address",
            "email",
            "firstname",
            "id",
            "lastname",
            "operation_date",
            "operation",
            "_rescued_data",
        ],
        "whereClause": ["id IS NOT NULL", "email is not NULL"],
        "partitionColumns": ["operation_date"],
        "cdcApplyChanges": json.dumps(silver_cdc_apply_changes),
        "version": "v1",
        "createDate": datetime.now,
        "createdBy": "dlt-meta-unittest",
        "updateDate": datetime.now,
        "updatedBy": "dlt-meta-unittest",
    }

    def setUp(self):
        """Set up initial resources for unit tests."""
        super().setUp()
        onboardDataFlowSpecs = OnboardDataflowspec(self.spark, self.onboarding_bronze_silver_params_map)
        onboardDataFlowSpecs.onboard_dataflow_specs()
        print("Onboarding completed")

    @patch.object(DataflowPipeline, "run_dlt", return_value={"called"})
    def test_invoke_dlt_pipeline_bronz_positive(self, run_dlt):
        """Test for brozne dlt pipeline."""
        database = self.onboarding_bronze_silver_params_map["database"]
        bronze_dataflow_table = self.onboarding_bronze_silver_params_map["bronze_dataflowspec_table"]
        self.spark.conf.set("bronze.group", "A1")
        self.spark.conf.set("layer", "bronze")
        self.spark.conf.set(
            "bronze.dataflowspecTable",
            f"{database}.{bronze_dataflow_table}",
        )
        DataflowPipeline.invoke_dlt_pipeline(self.spark, "bronze")
        assert run_dlt.called

    @patch.object(DataflowPipeline, "run_dlt", return_value={"called"})
    def test_invoke_dlt_pipeline_silver_positive(self, run_dlt):
        """Test for brozne dlt pipeline."""
        database = self.onboarding_bronze_silver_params_map["database"]
        silver_dataflow_table = self.onboarding_bronze_silver_params_map["silver_dataflowspec_table"]
        self.spark.conf.set("silver.group", "A1")
        self.spark.conf.set("layer", "silver")
        self.spark.conf.set(
            "silver.dataflowspecTable",
            f"{database}.{silver_dataflow_table}",
        )
        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customers_cdc")
         )
        transactions_parquet_df = self.spark.read.options(**options).json("tests/resources/data/transactions")
        (transactions_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.transactions_cdc")
         )

        DataflowPipeline.invoke_dlt_pipeline(self.spark, "silver")
        assert run_dlt.called

    @patch.object(DataflowPipeline, "read", return_value={"called"})
    def test_run_dlt_pipeline_silver_positive(self, read):
        """Test for silver dlt pipeline."""
        silver_spec_map = DataflowPipelineTests.silver_dataflow_spec_map
        source_details = {
            "sourceDetails": {"database": "bronze", "table": "customer", "path": "tests/resources/delta/customers"}
        }
        silver_spec_map.update(source_details)
        silver_dataflow_spec = SilverDataflowSpec(**silver_spec_map)
        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customer")
         )

        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )

        self.assertIsNotNone(dlt_data_flow.silver_schema)
        dlt_data_flow.run_dlt()
        assert read.called

    def test_dataflow_pipeline_constructor_negative(self):
        """Test dataflowpipelines consturctor with negative values."""
        with self.assertRaises(Exception):
            DataflowPipeline(
                self.spark,
                None,
                "inputView",
                None,
            )

    def test_dataflow_pipeline_read_bronze_negative(self):
        """Test dataflowpipeline reading bronze layer."""
        bronze_map = DataflowPipelineTests.bronze_dataflow_spec_map
        bronze_update_map = {"sourceFormat": "orc"}
        bronze_map.update(bronze_update_map)
        bronze_dataflow_spec = BronzeDataflowSpec(**bronze_map)
        dlt_data_flow = DataflowPipeline(
            self.spark,
            bronze_dataflow_spec,
            f"{bronze_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        with self.assertRaises(Exception):
            dlt_data_flow.read_bronze()

    def test_dataflow_pipeline_table_has_expectations_positive(self):
        """Test dataflow pipeline tables expectations."""
        bronze_dataflow_spec = BronzeDataflowSpec(**DataflowPipelineTests.bronze_dataflow_spec_map)
        dlt_data_flow = DataflowPipeline(
            self.spark,
            bronze_dataflow_spec,
            f"{bronze_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        self.assertIsNotNone(dlt_data_flow.table_has_expectations())

    def test_get_silver_schema_positive(self):
        """Test silver schema."""
        silver_spec_map = DataflowPipelineTests.silver_dataflow_spec_map
        source_details = {
            "sourceDetails": {"database": "bronze", "table": "customer", "path": "tests/resources/delta/customers"}
        }
        silver_spec_map.update(source_details)
        silver_dataflow_spec = SilverDataflowSpec(**silver_spec_map)
        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customer")
         )
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_schema = dlt_data_flow.get_silver_schema()
        self.assertIsNotNone(silver_schema)

    def test_get_silver_schema_where_clause(self):
        """Test silver schema."""
        silver_spec_map = DataflowPipelineTests.silver_dataflow_spec_map
        source_details = {
            "sourceDetails": {"database": "bronze", "table": "customer", "path": "tests/resources/delta/customers"}
        }
        silver_spec_map.update(source_details)
        silver_dataflow_spec = SilverDataflowSpec(**silver_spec_map)

        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customer")
         )

        silver_dataflow_spec.whereClause = None
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_schema = dlt_data_flow.get_silver_schema()
        self.assertIsNotNone(silver_schema)
        silver_dataflow_spec.whereClause = [" "]
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_schema = dlt_data_flow.get_silver_schema()
        self.assertIsNotNone(silver_schema)

    def test_read_silver_positive(self):
        """Test silver reader positive."""
        silver_spec_map = DataflowPipelineTests.silver_dataflow_spec_map
        source_details = {
            "sourceDetails": {"database": "bronze", "table": "customer", "path": "tests/resources/delta/customers"}
        }
        silver_spec_map.update(source_details)
        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customer")
         )
        silver_dataflow_spec = SilverDataflowSpec(**silver_spec_map)
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_df = dlt_data_flow.read_silver()
        self.assertIsNotNone(silver_df)

        silver_dataflow_spec.whereClause = None
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_df = dlt_data_flow.read_silver()
        self.assertIsNotNone(silver_df)
        silver_dataflow_spec.whereClause = [" "]
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_df = dlt_data_flow.read_silver()
        self.assertIsNotNone(silver_df)

    @patch.object(DataflowPipeline, "get_silver_schema", return_value={"called"})
    def test_read_silver_with_where(self, get_silver_schema):
        """Test silver reader positive."""
        silver_spec_map = DataflowPipelineTests.silver_dataflow_spec_map
        source_details = {
            "sourceDetails": {"database": "bronze", "table": "customer", "path": "tests/resources/delta/customers"}
        }
        silver_spec_map.update(source_details)
        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customer")
         )
        silver_dataflow_spec = SilverDataflowSpec(**silver_spec_map)
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        silver_df = dlt_data_flow.read_silver()
        self.assertIsNotNone(silver_df)
        assert get_silver_schema.called

    @patch.object(DataflowPipeline, "write_bronze_with_dqe", return_value={"called"})
    @patch.object(dlt, "expect_all_or_drop", return_value={"called"})
    def test_broze_write_dqe(self, expect_all_or_drop, write_bronze_with_dqe):
        bronze_dataflow_spec = BronzeDataflowSpec(**DataflowPipelineTests.bronze_dataflow_spec_map)
        dlt_data_flow = DataflowPipeline(
            self.spark,
            bronze_dataflow_spec,
            f"{bronze_dataflow_spec.targetDetails['table']}_inputView",
            f"{bronze_dataflow_spec.targetDetails['table']}_inputQView",
        )
        dlt_data_flow.write_bronze()
        assert write_bronze_with_dqe.called

    @patch.object(DataflowPipeline, "cdc_apply_changes", return_value={"called"})
    @patch.object(dlt, "expect_all_or_drop", return_value={"called"})
    def test_broze_write_cdc_apply_changes(self, expect_all_or_drop, cdc_apply_changes):
        bronze_dataflow_spec = BronzeDataflowSpec(**DataflowPipelineTests.bronze_dataflow_spec_map)
        cdc_apply_changes_json = """{
            "keys": [
                "id"
            ],
            "sequence_by": "operation_date",
            "scd_type": "1",
            "apply_as_deletes": "operation = 'DELETE'",
            "except_column_list": [
                "operation",
                "operation_date",
                "_rescued_data"
            ]
        }"""
        bronze_dataflow_spec.cdcApplyChanges = cdc_apply_changes_json
        dlt_data_flow = DataflowPipeline(
            self.spark,
            bronze_dataflow_spec,
            f"{bronze_dataflow_spec.targetDetails['table']}_inputView",
            f"{bronze_dataflow_spec.targetDetails['table']}_inputQView",
        )
        dlt_data_flow.write_bronze()
        assert cdc_apply_changes.called

    @patch.object(DataflowPipeline, "cdc_apply_changes", return_value={"called"})
    def test_cdc_apply_changes_scd_type2(self, cdc_apply_changes):
        silver_spec_map = DataflowPipelineTests.silver_dataflow_spec_map
        silver_dataflow_spec = SilverDataflowSpec(**silver_spec_map)
        silver_dataflow_spec.cdcApplyChanges = json.dumps(self.silver_cdc_apply_changes_scd2)
        self.spark.sql("CREATE DATABASE IF NOT EXISTS bronze")
        options = {"rescuedDataColumn": "_rescued_data", "inferColumnTypes": "true", "multiline": True}
        customers_parquet_df = self.spark.read.options(**options).json("tests/resources/data/customers")
        (customers_parquet_df.withColumn("_rescued_data", lit("Test")).write.format("delta")
            .mode("overwrite").saveAsTable("bronze.customer")
         )
        dlt_data_flow = DataflowPipeline(
            self.spark,
            silver_dataflow_spec,
            f"{silver_dataflow_spec.targetDetails['table']}_inputView",
            None,
        )
        dlt_data_flow.cdc_apply_changes()
        assert cdc_apply_changes.called
        dlt_data_flow.cdcApplyChanges.except_column_list = ["operation_date", "_rescued_data"]
        dlt_data_flow.cdc_apply_changes()
        assert cdc_apply_changes.called
        dlt_data_flow.cdc_apply_changes = None
        with self.assertRaises(Exception):
            dlt_data_flow.cdc_apply_changes()

    @patch('dlt.view', new_callable=MagicMock)
    def test_dlt_view_bronze_call(self, mock_view):
        mock_view.view.return_value = None
        bronze_dataflow_spec = BronzeDataflowSpec(
            **DataflowPipelineTests.bronze_dataflow_spec_map
        )
        view_name = f"{bronze_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        pipeline.read_bronze = MagicMock()
        pipeline.view_name = view_name
        pipeline.read()
        assert mock_view.called_once_with(
            pipeline.read_bronze,
            name=pipeline.view_name,
            comment=f"input dataset view for {pipeline.view_name}"
        )

    @patch('dlt.view', new_callable=MagicMock)
    def test_dlt_view_silver_call(self, mock_view):
        mock_view.view.return_value = None
        silver_dataflow_spec = SilverDataflowSpec(
            **DataflowPipelineTests.silver_dataflow_spec_map
        )
        view_name = f"{silver_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, silver_dataflow_spec, view_name, None)
        pipeline.read_bronze = MagicMock()
        pipeline.view_name = view_name
        pipeline.read()
        assert mock_view.called_once_with(
            pipeline.read_silver,
            name=pipeline.view_name,
            comment=f"input dataset view for {pipeline.view_name}"
        )

    @patch('dlt.table', new_callable=MagicMock)
    def test_dlt_write_bronze(self, mock_dlt_table):
        mock_dlt_table.table.return_value = None
        bronze_dataflow_spec = BronzeDataflowSpec(
            **DataflowPipelineTests.bronze_dataflow_spec_map
        )
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        bronze_dataflow_spec.cdcApplyChanges = None
        bronze_dataflow_spec.dataQualityExpectations = None
        view_name = f"{bronze_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        pipeline.read_bronze = MagicMock()
        pipeline.view_name = view_name
        target_path = None
        pipeline.write_bronze()
        assert mock_dlt_table.called_once_with(
            pipeline.write_to_delta,
            name=f"{bronze_dataflow_spec.targetDetails['table']}",
            partition_cols=DataflowSpecUtils.get_partition_cols(bronze_dataflow_spec.partitionColumns),
            table_properties=bronze_dataflow_spec.tableProperties,
            path=target_path,
            comment=f"bronze dlt table{bronze_dataflow_spec.targetDetails['table']}"
        )
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "False")
        target_path = bronze_dataflow_spec.targetDetails["path"]
        pipeline.write_bronze()
        assert mock_dlt_table.called_once_with(
            pipeline.write_to_delta,
            name=f"{bronze_dataflow_spec.targetDetails['table']}",
            partition_cols=DataflowSpecUtils.get_partition_cols(bronze_dataflow_spec.partitionColumns),
            table_properties=bronze_dataflow_spec.tableProperties,
            path=target_path,
            comment=f"bronze dlt table{bronze_dataflow_spec.targetDetails['table']}"
        )

    @patch('dlt.table', new_callable=MagicMock)
    def test_dlt_write_silver(self, mock_dlt_table):
        DataflowPipeline.get_silver_schema = MagicMock
        mock_dlt_table.table.return_value = None
        # Arrange
        silver_dataflow_spec = SilverDataflowSpec(
            **DataflowPipelineTests.silver_dataflow_spec_map
        )
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        view_name = f"{silver_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, silver_dataflow_spec, view_name, None)
        pipeline.read_bronze = MagicMock()
        pipeline.view_name = view_name
        target_path = None
        silver_dataflow_spec.cdcApplyChanges = None
        pipeline.write_silver()
        assert mock_dlt_table.called_once_with(
            pipeline.write_to_delta,
            name=f"{silver_dataflow_spec.targetDetails['table']}",
            partition_cols=DataflowSpecUtils.get_partition_cols(silver_dataflow_spec.partitionColumns),
            table_properties=silver_dataflow_spec.tableProperties,
            path=target_path,
            comment=f"silver dlt table{silver_dataflow_spec.targetDetails['table']}"
        )
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "False")
        target_path = silver_dataflow_spec.targetDetails["path"]
        pipeline.write_silver()
        assert mock_dlt_table.called_once_with(
            pipeline.write_to_delta,
            name=f"{silver_dataflow_spec.targetDetails['table']}",
            partition_cols=DataflowSpecUtils.get_partition_cols(silver_dataflow_spec.partitionColumns),
            table_properties=silver_dataflow_spec.tableProperties,
            path=target_path,
            comment=f"silver dlt table{silver_dataflow_spec.targetDetails['table']}"
        )

    @patch.object(DataflowPipeline, 'write_silver', new_callable=MagicMock)
    def test_dataflowpipeline_silver_write(self, mock_dfp):
        mock_dfp.write_bronze.return_value = None
        DataflowPipeline.get_silver_schema = MagicMock
        silver_dataflow_spec = SilverDataflowSpec(
            **DataflowPipelineTests.silver_dataflow_spec_map
        )
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        view_name = f"{silver_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, silver_dataflow_spec, view_name, None)
        pipeline.read_bronze = MagicMock()
        pipeline.view_name = view_name
        silver_dataflow_spec.cdcApplyChanges = None
        pipeline.write()
        assert mock_dfp.called

    @patch.object(DataflowPipeline, 'write_bronze', new_callable=MagicMock)
    def test_dataflowpipeline_bronze_write(self, mock_dfp):
        mock_dfp.write_bronze.return_value = None
        DataflowPipeline.get_silver_schema = MagicMock
        bronze_dataflow_spec = BronzeDataflowSpec(
            **DataflowPipelineTests.bronze_dataflow_spec_map
        )
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        view_name = f"{bronze_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        pipeline.read_bronze = MagicMock()
        pipeline.view_name = view_name
        bronze_dataflow_spec.cdcApplyChanges = None
        pipeline.write()
        assert mock_dfp.called

    @patch.object(PipelineReaders, 'read_dlt_cloud_files', mock_cloud_files=MagicMock)
    def test_dataflow_pipeline_read_bronze_cloudfiles(self, mock_cloud_files):
        mock_cloud_files.return_value = None
        bronze_dataflow_spec = BronzeDataflowSpec(
            **DataflowPipelineTests.bronze_dataflow_spec_map
        )
        bronze_dataflow_spec.sourceFormat = "cloudFiles"
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        bronze_dataflow_spec.cdcApplyChanges = None
        bronze_dataflow_spec.dataQualityExpectations = None
        view_name = f"{bronze_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        pipeline.read_bronze()
        assert mock_cloud_files.called
        bronze_dataflow_spec.sourceFormat = "delta"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        bronze_dataflow_spec.sourceFormat = "eventhub"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        bronze_dataflow_spec.sourceFormat = "kafka"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)

    @patch.object(PipelineReaders, 'read_dlt_delta', mock_read_dlt_delta=MagicMock)
    def test_dataflow_pipeline_read_bronze_delta(self, mock_read_dlt_delta):
        mock_read_dlt_delta.return_value = None
        bronze_dataflow_spec = BronzeDataflowSpec(
            **DataflowPipelineTests.bronze_dataflow_spec_map
        )
        bronze_dataflow_spec.sourceFormat = "delta"
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        bronze_dataflow_spec.cdcApplyChanges = None
        bronze_dataflow_spec.dataQualityExpectations = None
        view_name = f"{bronze_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        pipeline.read_bronze()
        assert mock_read_dlt_delta.called

    @patch.object(PipelineReaders, 'read_kafka', mock_read_kafka=MagicMock)
    def test_dataflow_pipeline_read_bronze_kafka(self, mock_read_kafka):
        mock_read_kafka.return_value = None
        bronze_dataflow_spec = BronzeDataflowSpec(
            **DataflowPipelineTests.bronze_dataflow_spec_map
        )
        bronze_dataflow_spec.sourceFormat = "kafka"
        self.spark.conf.set("spark.databricks.unityCatalog.enabled", "True")
        bronze_dataflow_spec.cdcApplyChanges = None
        bronze_dataflow_spec.dataQualityExpectations = None
        view_name = f"{bronze_dataflow_spec.targetDetails['table']}_inputView"
        pipeline = DataflowPipeline(self.spark, bronze_dataflow_spec, view_name, None)
        pipeline.read_bronze()
        assert mock_read_kafka.called
