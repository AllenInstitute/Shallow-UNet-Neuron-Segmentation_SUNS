# %%
import os
import numpy as np
import time
import h5py
import sys

from scipy.io import savemat, loadmat
import multiprocessing as mp

sys.path.insert(1, '..\\..') # the path containing "suns" folder
os.environ['KERAS_BACKEND'] = 'tensorflow'
# os.environ['CUDA_VISIBLE_DEVICES'] = '0' # Set which GPU to use. '-1' uses only CPU.

from suns.PostProcessing.evaluate import GetPerformance_Jaccard_2
from suns.run_suns import suns_batch


# %%
if __name__ == '__main__':
    list_name_video = ['J115', 'J123', 'K53', 'YST']
    list_radius = [8,10,8,6] # 
    list_rate_hz = [30,30,30,10] # 
    list_decay_time = [0.4, 0.5, 0.4, 0.75]
    Dimens = [(224,224),(216,152), (248,248),(120,88)]
    list_nframes = [90000, 41000, 116043, 3000]
    ID_part = ['_part11', '_part12', '_part21', '_part22']
    list_Mag = [x/8 for x in list_radius]
    list_thred_std = [6,6,6,3]

    # %% setting parameters
    useSF=True # True if spatial filtering is used in pre-processing.
    useTF=True # True if temporal filtering is used in pre-processing.
    useSNR=True # True if pixel-by-pixel SNR normalization filtering is used in pre-processing.
    med_subtract=False # True if the spatial median of every frame is subtracted before temporal filtering.
        # Can only be used when spatial filtering is not used. 
    prealloc=True # True if pre-allocate memory space for large variables in pre-processing. 
            # Achieve faster speed at the cost of higher memory occupation.
    batch_size_eval = 200 # batch size in CNN inference
    useWT=False # True if using additional watershed
    display=True # True if display information about running time 

    for ind_video in range(0,4): # [3]: # 
        name_video = list_name_video[ind_video]
        # file names of the ".h5" files storing the raw videos. 
        list_Exp_ID = [name_video+x for x in ID_part]
        # folder of the raw videos
        dir_video = 'F:\\CaImAn data\\WEBSITE\\divided_data\\'+name_video+'\\'
        # folder of the ".mat" files stroing the GT masks in sparse 2D matrices
        dir_GTMasks = dir_video + 'GT Masks\\FinalMasks_' 

        dir_parent = dir_video + 'complete\\' # folder to save all the processed data
        dir_output = dir_parent + 'output_masks\\' # folder to save the segmented masks and the performance scores
        dir_params = dir_parent + 'output_masks\\' # folder of the optimized hyper-parameters
        weights_path = dir_parent + 'Weights\\' # folder of the trained CNN
        if not os.path.exists(dir_output):
            os.makedirs(dir_output) 

        # %% pre-processing parameters
        nn = list_nframes[ind_video] 
        gauss_filt_size = 50*list_Mag[ind_video] # standard deviation of the spatial Gaussian filter in pixels
        num_median_approx = 1000 # number of frames used to caluclate median and median-based standard deviation
        dims = (Lx, Ly) = Dimens[ind_video] # lateral dimensions of the video
        filename_TF_template = name_video + '_spike_tempolate.h5'

        h5f = h5py.File(filename_TF_template,'r')
        Poisson_filt = np.array(h5f['filter_tempolate']).squeeze().astype('float32')
        Poisson_filt = Poisson_filt[Poisson_filt>np.exp(-1)] # temporal filter kernel
        # dictionary of pre-processing parameters
        Params_pre = {'gauss_filt_size':gauss_filt_size, 'num_median_approx':num_median_approx, 
            'nn':nn, 'Poisson_filt': Poisson_filt}

        p = mp.Pool()
        list_CV = list(range(0,4))
        num_CV = len(list_CV)
        # arrays to save the recall, precision, F1, total processing time, and average processing time per frame
        list_Recall = np.zeros((num_CV, 1))
        list_Precision = np.zeros((num_CV, 1))
        list_F1 = np.zeros((num_CV, 1))
        list_time = np.zeros((num_CV, 4))
        list_time_frame = np.zeros((num_CV, 4))


        for CV in list_CV:
            Exp_ID = list_Exp_ID[CV]
            print('Video ', Exp_ID)
            filename_CNN = weights_path+'Model_CV{}.h5'.format(CV) # The path of the CNN model.

            # load optimal post-processing parameters
            Optimization_Info = loadmat(dir_params+'Optimization_Info_{}.mat'.format(CV))
            Params_post_mat = Optimization_Info['Params'][0]
            # dictionary of all optimized post-processing parameters.
            Params_post={
                # minimum area of a neuron (unit: pixels).
                'minArea': Params_post_mat['minArea'][0][0,0], 
                # average area of a typical neuron (unit: pixels) 
                'avgArea': Params_post_mat['avgArea'][0][0,0],
                # uint8 threshould of probablity map (uint8 variable, = float probablity * 256 - 1.5)
                'thresh_pmap': Params_post_mat['thresh_pmap'][0][0,0], 
                # values higher than "thresh_mask" times the maximum value of the mask are set to one.
                'thresh_mask': Params_post_mat['thresh_mask'][0][0,0], 
                # maximum COM distance of two masks to be considered the same neuron in the initial merging (unit: pixels)
                'thresh_COM0': Params_post_mat['thresh_COM0'][0][0,0], 
                # maximum COM distance of two masks to be considered the same neuron (unit: pixels)
                'thresh_COM': Params_post_mat['thresh_COM'][0][0,0], 
                # minimum IoU of two masks to be considered the same neuron
                'thresh_IOU': Params_post_mat['thresh_IOU'][0][0,0], 
                # minimum consume ratio of two masks to be considered the same neuron
                'thresh_consume': Params_post_mat['thresh_consume'][0][0,0], 
                # minimum consecutive number of frames of active neurons
                'cons':Params_post_mat['cons'][0][0,0]}

            # The entire process of SUNS batch
            Masks, Masks_2, time_total, time_frame = suns_batch(
                dir_video, Exp_ID, filename_CNN, Params_pre, Params_post, dims, batch_size_eval, \
                useSF=useSF, useTF=useTF, useSNR=useSNR, med_subtract=med_subtract, \
                useWT=useWT, prealloc=prealloc, display=display, p=p)

            # %% Evaluation of the segmentation accuracy compared to manual ground truth
            filename_GT = dir_GTMasks + Exp_ID + '_sparse.mat'
            data_GT=loadmat(filename_GT)
            GTMasks_2 = data_GT['GTMasks_2'].transpose()
            (Recall,Precision,F1) = GetPerformance_Jaccard_2(GTMasks_2, Masks_2, ThreshJ=0.5)
            print({'Recall':Recall, 'Precision':Precision, 'F1':F1})
            savemat(dir_output+'Output_Masks_{}.mat'.format(Exp_ID), {'Masks_2':Masks_2})

            # %% Save recall, precision, F1, total processing time, and average processing time per frame
            list_Recall[CV] = Recall
            list_Precision[CV] = Precision
            list_F1[CV] = F1
            list_time[CV] = time_total
            list_time_frame[CV] = time_frame

            Info_dict = {'list_Recall':list_Recall, 'list_Precision':list_Precision, 'list_F1':list_F1, 
                'list_time':list_time, 'list_time_frame':list_time_frame}
            savemat(dir_output+'Output_Info_All.mat', Info_dict)

        p.close()


