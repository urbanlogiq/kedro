from pathlib import Path, PurePosixPath

import pandas as pd
import pytest
from adlfs import AzureBlobFileSystem
from fsspec.implementations.http import HTTPFileSystem
from fsspec.implementations.local import LocalFileSystem
from gcsfs import GCSFileSystem
from pandas.testing import assert_frame_equal
from s3fs.core import S3FileSystem

from kedro.extras.datasets.pandas import XMLDataSet
from kedro.io import DataSetError
from kedro.io.core import PROTOCOL_DELIMITER, Version


@pytest.fixture
def filepath_xml(tmp_path):
    return (tmp_path / "test.xml").as_posix()


@pytest.fixture
def xml_data_set(filepath_xml, load_args, save_args, fs_args):
    return XMLDataSet(
        filepath=filepath_xml,
        load_args=load_args,
        save_args=save_args,
        fs_args=fs_args,
    )


@pytest.fixture
def versioned_xml_data_set(filepath_xml, load_version, save_version):
    return XMLDataSet(
        filepath=filepath_xml, version=Version(load_version, save_version)
    )


@pytest.fixture
def dummy_dataframe():
    return pd.DataFrame({"col1": [1, 2], "col2": [4, 5], "col3": [5, 6]})


class TestXMLDataSet:
    def test_save_and_load(self, xml_data_set, dummy_dataframe):
        """Test saving and reloading the data set."""
        xml_data_set.save(dummy_dataframe)
        reloaded = xml_data_set.load()
        assert_frame_equal(dummy_dataframe, reloaded)

    def test_exists(self, xml_data_set, dummy_dataframe):
        """Test `exists` method invocation for both existing and
        nonexistent data set."""
        assert not xml_data_set.exists()
        xml_data_set.save(dummy_dataframe)
        assert xml_data_set.exists()

    @pytest.mark.parametrize(
        "load_args", [{"k1": "v1", "index": "value"}], indirect=True
    )
    def test_load_extra_params(self, xml_data_set, load_args):
        """Test overriding the default load arguments."""
        for key, value in load_args.items():
            assert xml_data_set._load_args[key] == value

    @pytest.mark.parametrize(
        "save_args", [{"k1": "v1", "index": "value"}], indirect=True
    )
    def test_save_extra_params(self, xml_data_set, save_args):
        """Test overriding the default save arguments."""
        for key, value in save_args.items():
            assert xml_data_set._save_args[key] == value

    @pytest.mark.parametrize(
        "load_args,save_args",
        [
            ({"storage_options": {"a": "b"}}, {}),
            ({}, {"storage_options": {"a": "b"}}),
            ({"storage_options": {"a": "b"}}, {"storage_options": {"x": "y"}}),
        ],
    )
    def test_storage_options_dropped(self, load_args, save_args, caplog, tmp_path):
        filepath = str(tmp_path / "test.csv")

        ds = XMLDataSet(filepath=filepath, load_args=load_args, save_args=save_args)

        records = [r for r in caplog.records if r.levelname == "WARNING"]
        expected_log_message = (
            f"Dropping 'storage_options' for {filepath}, "
            f"please specify them under 'fs_args' or 'credentials'."
        )
        assert records[0].getMessage() == expected_log_message
        assert "storage_options" not in ds._save_args
        assert "storage_options" not in ds._load_args

    def test_load_missing_file(self, xml_data_set):
        """Check the error when trying to load missing file."""
        pattern = r"Failed while loading data from data set XMLDataSet\(.*\)"
        with pytest.raises(DataSetError, match=pattern):
            xml_data_set.load()

    @pytest.mark.parametrize(
        "filepath,instance_type,credentials,load_path",
        [
            ("s3://bucket/file.xml", S3FileSystem, {}, "s3://bucket/file.xml"),
            ("file:///tmp/test.xml", LocalFileSystem, {}, "/tmp/test.xml"),
            ("/tmp/test.xml", LocalFileSystem, {}, "/tmp/test.xml"),
            ("gcs://bucket/file.xml", GCSFileSystem, {}, "gcs://bucket/file.xml"),
            (
                "https://example.com/file.xml",
                HTTPFileSystem,
                {},
                "https://example.com/file.xml",
            ),
            (
                "abfs://bucket/file.csv",
                AzureBlobFileSystem,
                {"account_name": "test", "account_key": "test"},
                "abfs://bucket/file.csv",
            ),
        ],
    )
    def test_protocol_usage(
        self, filepath, instance_type, credentials, load_path, mocker
    ):
        data_set = XMLDataSet(filepath=filepath, credentials=credentials)
        assert isinstance(data_set._fs, instance_type)

        path = filepath.split(PROTOCOL_DELIMITER, 1)[-1]

        assert str(data_set._filepath) == path
        assert isinstance(data_set._filepath, PurePosixPath)

        mock_pandas_call = mocker.patch("pandas.read_xml")
        data_set.load()
        assert mock_pandas_call.call_count == 1
        assert mock_pandas_call.call_args_list[0][0][0] == load_path

    def test_catalog_release(self, mocker):
        fs_mock = mocker.patch("fsspec.filesystem").return_value
        filepath = "test.xml"
        data_set = XMLDataSet(filepath=filepath)
        data_set.release()
        fs_mock.invalidate_cache.assert_called_once_with(filepath)


class TestXMLDataSetVersioned:
    def test_version_str_repr(self, load_version, save_version):
        """Test that version is in string representation of the class instance
        when applicable."""
        filepath = "test.xml"
        ds = XMLDataSet(filepath=filepath)
        ds_versioned = XMLDataSet(
            filepath=filepath, version=Version(load_version, save_version)
        )
        assert filepath in str(ds)
        assert "version" not in str(ds)

        assert filepath in str(ds_versioned)
        ver_str = f"version=Version(load={load_version}, save='{save_version}')"
        assert ver_str in str(ds_versioned)
        assert "XMLDataSet" in str(ds_versioned)
        assert "XMLDataSet" in str(ds)
        assert "protocol" in str(ds_versioned)
        assert "protocol" in str(ds)

    def test_save_and_load(self, versioned_xml_data_set, dummy_dataframe):
        """Test that saved and reloaded data matches the original one for
        the versioned data set."""
        versioned_xml_data_set.save(dummy_dataframe)
        reloaded_df = versioned_xml_data_set.load()
        assert_frame_equal(dummy_dataframe, reloaded_df)

    def test_no_versions(self, versioned_xml_data_set):
        """Check the error if no versions are available for load."""
        pattern = r"Did not find any versions for XMLDataSet\(.+\)"
        with pytest.raises(DataSetError, match=pattern):
            versioned_xml_data_set.load()

    def test_exists(self, versioned_xml_data_set, dummy_dataframe):
        """Test `exists` method invocation for versioned data set."""
        assert not versioned_xml_data_set.exists()
        versioned_xml_data_set.save(dummy_dataframe)
        assert versioned_xml_data_set.exists()

    def test_prevent_overwrite(self, versioned_xml_data_set, dummy_dataframe):
        """Check the error when attempting to override the data set if the
        corresponding hdf file for a given save version already exists."""
        versioned_xml_data_set.save(dummy_dataframe)
        pattern = (
            r"Save path \'.+\' for XMLDataSet\(.+\) must "
            r"not exist if versioning is enabled\."
        )
        with pytest.raises(DataSetError, match=pattern):
            versioned_xml_data_set.save(dummy_dataframe)

    @pytest.mark.parametrize(
        "load_version", ["2019-01-01T23.59.59.999Z"], indirect=True
    )
    @pytest.mark.parametrize(
        "save_version", ["2019-01-02T00.00.00.000Z"], indirect=True
    )
    def test_save_version_warning(
        self, versioned_xml_data_set, load_version, save_version, dummy_dataframe
    ):
        """Check the warning when saving to the path that differs from
        the subsequent load path."""
        pattern = (
            rf"Save version '{save_version}' did not match "
            rf"load version '{load_version}' for XMLDataSet\(.+\)"
        )
        with pytest.warns(UserWarning, match=pattern):
            versioned_xml_data_set.save(dummy_dataframe)

    def test_http_filesystem_no_versioning(self):
        pattern = r"HTTP\(s\) DataSet doesn't support versioning\."

        with pytest.raises(DataSetError, match=pattern):
            XMLDataSet(
                filepath="https://example.com/file.xml", version=Version(None, None)
            )

    def test_versioning_existing_dataset(
        self, xml_data_set, versioned_xml_data_set, dummy_dataframe
    ):
        """Check the error when attempting to save a versioned dataset on top of an
        already existing (non-versioned) dataset."""
        xml_data_set.save(dummy_dataframe)
        assert xml_data_set.exists()
        assert xml_data_set._filepath == versioned_xml_data_set._filepath
        pattern = (
            f"(?=.*file with the same name already exists in the directory)"
            f"(?=.*{versioned_xml_data_set._filepath.parent.as_posix()})"
        )
        with pytest.raises(DataSetError, match=pattern):
            versioned_xml_data_set.save(dummy_dataframe)

        # Remove non-versioned dataset and try again
        Path(xml_data_set._filepath.as_posix()).unlink()
        versioned_xml_data_set.save(dummy_dataframe)
        assert versioned_xml_data_set.exists()