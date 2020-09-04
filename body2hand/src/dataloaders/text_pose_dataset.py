import torch
from torch.utils.data import Dataset

from glob import glob
import json
import time
from tokenizers import Tokenizer




BODY_HEAD_KEYPOINTS = [0, 1, 2, 3, 4, 5, 6, 7, 15, 16, 17, 18]

def format_keypoints(keypoints, n_dim=2):
    '''
    Changes from [x1, y1, c1, x2, y2, c2, ...] to [[x1, y1, c1], [x2, y2, c2], ...]
    being x, y the 2D coords and c the openpose confidence
    :param keypoints: keypoints with input format
    :param n_dim: dimnensionality of the coordenates
    :return: keypoints with good format
    '''
    n_dim += 1
    return [keypoints[n_dim * i:n_dim * i + n_dim] for i in
                         range(len(keypoints) // n_dim)]


def load_keypoints(json_path):

    data = json.load(open(json_path))


    body_kp = format_keypoints(data["people"][0]["pose_keypoints_2d"])
    #Filer out legs
    body_kp = [body_kp[i] for i in BODY_HEAD_KEYPOINTS]

    l_hand_kp = format_keypoints(data["people"][0]["hand_left_keypoints_2d"])
    r_hand_kp = format_keypoints(data["people"][0]["hand_right_keypoints_2d"])

    # Separate confidence and keypoints
    r_hand_kp, r_hand_conf = [x[:2] for x in r_hand_kp], [x[2] for x in r_hand_kp]
    l_hand_kp, l_hand_conf = [x[:2] for x in l_hand_kp], [x[2] for x in l_hand_kp]
    body_kp, body_conf = [x[:2] for x in body_kp], [x[2] for x in body_kp]

    return r_hand_kp, r_hand_conf, l_hand_kp, l_hand_conf, body_kp, body_conf


class PoseDataset(Dataset):
    def __init__(self, metadata_file, max_frames, transform):
        super().__init__()
        if isinstance(metadata_file, str):
            self.data = json.load(open(metadata_file))
        elif isinstance(metadata_file, list):
            self.data = metadata_file
        self.max_frames = max_frames

        self.transform = transform

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):

        #print("Start get item")

        # TODO: Get right and left hand
        # TODO: Random crop of sequence instead of clipping
        # TODO: Only load the ones that are going to be used

        metadata = self.data[idx]

        text = metadata["text"]
        jsons_folder = metadata["frame_jsons_folder"]

        all_jsons = glob(jsons_folder + "/*")

        assert len(all_jsons) > 0

        all_jsons.sort()
        item = {
            "body_kp":[],
            "body_conf":[],
            "right_hand_kp":[],
            "right_hand_conf":[],
            "left_hand_kp":[],
            "left_hand_conf":[],
            "n_frames": min(metadata["n_frames"], self.max_frames),
            "json_paths":[],
            "text": metadata["text"]
        }




        for json_file in all_jsons:
            r_hand_kp, r_hand_conf, l_hand_kp, l_hand_conf, body_kp, body_conf = load_keypoints(json_file)
            item["body_kp"].append(body_kp)
            item["right_hand_kp"].append(r_hand_kp)
            item["left_hand_kp"].append(l_hand_kp)
            item["body_conf"].append(body_conf)
            item["right_hand_conf"].append(r_hand_conf)
            item["left_hand_conf"].append(l_hand_conf)
            item["json_paths"].append(json_file)

        # Pad sequence to max len
        while len(item["body_kp"]) < self.max_frames:
            item["body_kp"].append(item["body_kp"][0])
            item["right_hand_kp"].append(item["right_hand_kp"][0])
            item["left_hand_kp"].append(item["left_hand_kp"][0])
            item["body_conf"].append(item["body_conf"][0])
            item["right_hand_conf"].append(item["right_hand_conf"][0])
            item["left_hand_conf"].append(item["left_hand_conf"][0])

        # Clip sequence to max len
        item["body_kp"] = item["body_kp"][:self.max_frames]
        item["right_hand_kp"] = item["right_hand_kp"][:self.max_frames]
        item["left_hand_kp"] = item["left_hand_kp"][:self.max_frames]
        item["body_conf"] = item["body_conf"][:self.max_frames]
        item["right_hand_conf"] = item["right_hand_conf"][:self.max_frames]
        item["left_hand_conf"] = item["left_hand_conf"][:self.max_frames]
        item["json_paths"] = item["json_paths"][:self.max_frames]

        # To tensor
        item["body_kp"] = torch.tensor(item["body_kp"]).float()
        item["right_hand_kp"] = torch.tensor(item["right_hand_kp"]).float()
        item["left_hand_kp"] = torch.tensor(item["left_hand_kp"]).float()
        item["body_conf"] = torch.tensor(item["body_conf"]).float()
        item["right_hand_conf"] = torch.tensor(item["right_hand_conf"]).float()
        item["left_hand_conf"] = torch.tensor(item["left_hand_conf"]).float()

        if self.transform:
            item = self.transform(item)

        return item


class TextPoseDataset(Dataset):


    def __init__(self, metadata_file, max_frames, transform,
                 tokenizer_path, max_tokens):
        super().__init__()
        self.data = json.load(open(metadata_file))
        self.max_frames = max_frames
        self.transform = transform

        tokenizer = Tokenizer.from_file(tokenizer_path)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):

        #print("Start get item")

        metadata = self.data[idx]

        jsons_folder = metadata["frame_jsons_folder"]

        item = self.load_pose(jsons_folder)
        item = self.clip_and_pad(item)

        item["text"] = metadata["text"]
        item["n_frames"] = min(metadata["n_frames"], self.max_frames)

        if self.transform:
            item = self.transform(item)

        return item

    def load_pose(self, jsons_folder):
        all_jsons = glob(jsons_folder + "/*")

        assert len(all_jsons) > 0

        all_jsons.sort()
        item = {
            "body_kp": [],
            "body_conf": [],
            "right_hand_kp": [],
            "right_hand_conf": [],
            "left_hand_kp": [],
            "left_hand_conf": []
            # "text":metadata["text"]
        }

        for json_file in all_jsons:
            r_hand_kp, r_hand_conf, l_hand_kp, l_hand_conf, body_kp, body_conf = load_keypoints(
                json_file)
            item["body_kp"].append(body_kp)
            item["right_hand_kp"].append(r_hand_kp)
            item["left_hand_kp"].append(l_hand_kp)
            item["body_conf"].append(body_conf)
            item["right_hand_conf"].append(r_hand_conf)
            item["left_hand_conf"].append(l_hand_conf)

        return item

    def clip_and_pad(self, item):
        # Pad sequence to max len
        while len(item["body_kp"]) < self.max_frames:
            item["body_kp"].append(item["body_kp"][0])
            item["right_hand_kp"].append(item["right_hand_kp"][0])
            item["left_hand_kp"].append(item["left_hand_kp"][0])
            item["body_conf"].append(item["body_conf"][0])
            item["right_hand_conf"].append(item["right_hand_conf"][0])
            item["left_hand_conf"].append(item["left_hand_conf"][0])

        # Clip sequence to max len
        item["body_kp"] = item["body_kp"][:self.max_frames]
        item["right_hand_kp"] = item["right_hand_kp"][:self.max_frames]
        item["left_hand_kp"] = item["left_hand_kp"][:self.max_frames]
        item["body_conf"] = item["body_conf"][:self.max_frames]
        item["right_hand_conf"] = item["right_hand_conf"][:self.max_frames]
        item["left_hand_conf"] = item["left_hand_conf"][:self.max_frames]

        return item


