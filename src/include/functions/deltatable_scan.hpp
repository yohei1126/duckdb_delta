//===----------------------------------------------------------------------===//
//                         DuckDB
//
// functions/deltatable_scan.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "delta_utils.hpp"
#include "duckdb/common/multi_file_reader.hpp"

namespace duckdb {

struct DeltaFileMetaData {
    idx_t delta_snapshot_version;
    idx_t file_number;

    UniqueKernelPointer <ffi::KernelBoolSlice> selection_vector;

    case_insensitive_map_t<string> partition_map;
};

//! The DeltaTableSnapshot implements the MultiFileList API to allow injecting it into the regular DuckDB parquet scan
struct DeltaTableSnapshot : public MultiFileList {
    DeltaTableSnapshot(ClientContext &context, const string &path);
    string GetPath();
    static string ToDuckDBPath(const string &raw_path);
    static string ToDeltaPath(const string &raw_path);

    //! MultiFileList API
public:
    void Bind(vector<LogicalType> &return_types, vector<string> &names);
    unique_ptr<MultiFileList> ComplexFilterPushdown(ClientContext &context,
                                                            const MultiFileReaderOptions &options, LogicalGet &get,
                                                            vector<unique_ptr<Expression>> &filters) override;
    vector<string> GetAllFiles() override;
    FileExpandResult GetExpandResult() override;
    idx_t GetTotalFileCount() override;

protected:
    //! Get the i-th expanded file
    string GetFile(idx_t i) override;

protected:
    // TODO: How to guarantee we only call this after the filter pushdown?
    void InitializeFiles();

// TODO: change back to protected
public:
    idx_t version;

    //! Delta Kernel Structures
    const ffi::SnapshotHandle *snapshot;
    const ffi::ExternEngineHandle *table_client;
    ffi::Scan* scan;
    ffi::GlobalScanState *global_state;
    UniqueKernelPointer <ffi::KernelScanDataIterator> scan_data_iterator;

    //! Names
    vector<string> names;

    //! Metadata map for files
    vector<DeltaFileMetaData> metadata;

    //! Current file list resolution state
    bool initialized = false;
    bool files_exhausted = false;
    vector<string> resolved_files;
    TableFilterSet table_filters;

    ClientContext &context;
};

struct DeltaMultiFileReaderGlobalState : public MultiFileReaderGlobalState {
    DeltaMultiFileReaderGlobalState(vector<LogicalType> extra_columns_p, optional_ptr<const MultiFileList> file_list_p) : MultiFileReaderGlobalState(extra_columns_p, file_list_p) {
    }
    //! The idx of the file number column in the result chunk
    idx_t delta_file_number_idx = DConstants::INVALID_INDEX;
    //! The idx of the file_row_number column in the result chunk
    idx_t file_row_number_idx = DConstants::INVALID_INDEX;

    void SetColumnIdx(const string &column, idx_t idx);
};

struct DeltaMultiFileReader : public MultiFileReader {
    static unique_ptr<MultiFileReader> CreateInstance();
    //! Return a DeltaTableSnapshot
    unique_ptr<MultiFileList> CreateFileList(ClientContext &context, const vector<string> &paths,
                   FileGlobOptions options) override;

    //! Override the regular parquet bind using the MultiFileReader Bind. The bind from these are what DuckDB's file
    //! readers will try read
    bool Bind(MultiFileReaderOptions &options, MultiFileList &files,
              vector<LogicalType> &return_types, vector<string> &names, MultiFileReaderBindData &bind_data) override;

    //! Override the Options bind
    void BindOptions(MultiFileReaderOptions &options, MultiFileList &files,
                                        vector<LogicalType> &return_types, vector<string> &names, MultiFileReaderBindData& bind_data) override;

    void CreateNameMapping(const string &file_name, const vector<LogicalType> &local_types,
                      const vector<string> &local_names, const vector<LogicalType> &global_types,
                      const vector<string> &global_names, const vector<column_t> &global_column_ids,
                      MultiFileReaderData &reader_data, const string &initial_file,
                      optional_ptr<MultiFileReaderGlobalState> global_state);

    unique_ptr<MultiFileReaderGlobalState> InitializeGlobalState(ClientContext &context, const MultiFileReaderOptions &file_options,
                          const MultiFileReaderBindData &bind_data, const MultiFileList &file_list,
                          const vector<LogicalType> &global_types, const vector<string> &global_names,
                          const vector<column_t> &global_column_ids) override;

    void FinalizeBind(const MultiFileReaderOptions &file_options, const MultiFileReaderBindData &options,
                                       const string &filename, const vector<string> &local_names,
                                       const vector<LogicalType> &global_types, const vector<string> &global_names,
                                       const vector<column_t> &global_column_ids, MultiFileReaderData &reader_data,
                                       ClientContext &context, optional_ptr<MultiFileReaderGlobalState> global_state) override;

    //! Override the FinalizeChunk method
    void FinalizeChunk(ClientContext &context, const MultiFileReaderBindData &bind_data,
                       const MultiFileReaderData &reader_data, DataChunk &chunk, optional_ptr<MultiFileReaderGlobalState> global_state) override;

    //! Override the ParseOption call to parse delta_scan specific options
    bool ParseOption(const string &key, const Value &val, MultiFileReaderOptions &options,
                                        ClientContext &context) override;
};

} // namespace duckdb
