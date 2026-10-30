#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

from rag.flow.base import ProcessBase, ProcessParamBase
from rag.flow.document_metadata.metadata import attach_document_metadata, extract_document_metadata


class DocumentMetadataParam(ProcessParamBase):
    def check(self):
        pass


class DocumentMetadata(ProcessBase):
    component_name = "DocumentMetadata"

    async def _invoke(self, **kwargs):
        chunks = kwargs.get("chunks")
        if chunks is None and kwargs.get("output_format") == "json":
            chunks = kwargs.get("json")

        filename = kwargs.get("name") or ""
        metadata = extract_document_metadata(filename)
        self.callback(0.5, message=f"Extracted document metadata fields: {', '.join(metadata)}")
        self.set_output("output_format", "chunks")
        self.set_output("chunks", attach_document_metadata(chunks, filename))
