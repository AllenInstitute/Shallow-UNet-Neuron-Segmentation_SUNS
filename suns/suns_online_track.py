# %%
import os
import cv2
import math
import numpy as np
import time
import h5py
import sys
import pyfftw
from scipy import sparse

from scipy.io import savemat, loadmat
import multiprocessing as mp

sys.path.insert(1, '..\\PreProcessing')
sys.path.insert(1, '..\\Network')
sys.path.insert(1, '..\\neuron_post')
sys.path.insert(1, '..\\Online')
os.environ['KERAS_BACKEND'] = 'tensorflow'
# os.environ['CUDA_VISIBLE_DEVICES'] = '0' # Set which GPU to use. '-1' uses only CPU.

from shallow_unet import get_shallow_unet
import functions_online
import functions_init
import par_online
from seperate_multi import separateNeuron


# %%
def suns_online_track(filename_video, filename_CNN, Params_pre, Params_post, dims, \
        frames_init, merge_every, batch_size_init=1, useSF=True, useTF=True, useSNR=True, \
        useWT=False, prealloc=True, display=True, useMP=True, p=None):
    '''The complete SUNS online procedure.

    Inputs: 
        filename_video (str): The path of the file of the input video.
            The file must be a ".h5" file, with dataset "mov" being the input video (shape = (T0,Lx0,Ly0)).
        filename_CNN (str): The path of the CNN model. 
        Params_pre (dict): Parameters for pre-processing.
            Params_pre['gauss_filt_size'] (float): The standard deviation of the spatial Gaussian filter in pixels
            Params_pre['Poisson_filt'] (1D numpy.ndarray of float32): The temporal filter kernel
            Params_pre['num_median_approx'] (int): Number of frames used to compute 
                the median and median-based standard deviation
            Params_pre['nn'] (int): Number of frames at the beginning of the video to be processed.
                The remaining video is not considered a part of the input video.
        Params_post (dict): Parameters for post-processing.
            Params_post['minArea']: Minimum area of a valid neuron mask (unit: pixels).
            Params_post['avgArea']: The typical neuron area (unit: pixels).
            Params_post['thresh_pmap']: The probablity threshold. Values higher than thresh_pmap are active pixels. 
                It is stored in uint8, so it should be converted to float32 before using.
            Params_post['thresh_mask']: Threashold to binarize the real-number mask.
            Params_post['thresh_COM0']: Threshold of COM distance (unit: pixels) used for the first COM-based merging. 
            Params_post['thresh_COM']: Threshold of COM distance (unit: pixels) used for the second COM-based merging. 
            Params_post['thresh_IOU']: Threshold of IOU used for merging neurons.
            Params_post['thresh_consume']: Threshold of consume ratio used for merging neurons.
            Params_post['cons']: Minimum number of consecutive frames that a neuron should be active for.
        dims (tuplel of int, shape = (2,)): lateral dimension of the raw video.
        frames_init (int): Number of frames used for initialization.
        merge_every (int): SUNS online merge the newly segmented frames every "merge_every" frames.
        batch_size_init (int, default to 1): batch size of CNN inference for initialization frames.
        useSF (bool, default to True): True if spatial filtering is used.
        useTF (bool, default to True): True if temporal filtering is used.
        useSNR (bool, default to True): True if pixel-by-pixel SNR normalization filtering is used.
        useWT (bool, default to False): Indicator of whether watershed is used. 
        prealloc (bool, default to True): True if pre-allocate memory space for large variables. 
            Achieve faster speed at the cost of higher memory occupation.
        display (bool, default to True): Indicator of whether to show intermediate information
        useMP (bool, defaut to True): indicator of whether multiprocessing is used to speed up. 
        p (multiprocessing.Pool, default to None): 

    Outputs:
        Masks (3D numpy.ndarray of bool, shape = (n,Lx,Ly)): the final segmented masks. 
        Masks_2 (scipy.csr_matrix of bool, shape = (n,Lx*Ly)): the final segmented masks in the form of sparse matrix. 
        time_total (list of float, shape = (3,)): the total time spent 
            for initalization, online processing, and total processing
        time_frame (list of float, shape = (3,)): the average time spent on every frame
            for initalization, online processing, and total processing
    '''
    if display:
        start = time.time()
    (Lx, Ly) = dims
    # zero-pad the lateral dimensions to multiples of 8, suitable for CNN
    rowspad = math.ceil(Lx/8)*8
    colspad = math.ceil(Ly/8)*8
    dimspad = (rowspad, colspad)

    Poisson_filt = Params_pre['Poisson_filt']
    gauss_filt_size = Params_pre['gauss_filt_size']
    nn = Params_pre['nn']
    leng_tf = Poisson_filt.size
    leng_past = 2*leng_tf # number of past frames stored for temporal filtering
    list_time_per = np.zeros(nn)

    # Load CNN model
    fff = get_shallow_unet()
    fff.load_weights(filename_CNN)
    # run CNN inference once to warm up
    init_imgs = np.zeros((batch_size_init, Lx, Ly, 1), dtype='float32')
    init_masks = np.zeros((batch_size_init, Lx, Ly, 1), dtype='uint8')
    fff.evaluate(init_imgs, init_masks, batch_size=batch_size_init)
    del init_imgs, init_masks

    # load optimal post-processing parameters
    minArea = Params_post['minArea']
    avgArea = Params_post['avgArea']
    # thresh_pmap = Params_post['thresh_pmap']
    thresh_mask = Params_post['thresh_mask']
    # thresh_COM0 = Params_post['thresh_COM0']
    # thresh_COM = Params_post['thresh_COM']
    thresh_IOU = Params_post['thresh_IOU']
    thresh_consume = Params_post['thresh_consume']
    # cons = Params_post['cons']
    thresh_pmap_float = (Params_post['thresh_pmap']+1.5)/256
    # thresh_pmap_float = (Params_post['thresh_pmap']+1)/256 # for published version


    # Spatial filtering preparation
    if useSF==True:
        # lateral dimensions slightly larger than the raw video but faster for FFT
        rows1 = cv2.getOptimalDFTSize(rowspad)
        cols1 = cv2.getOptimalDFTSize(colspad)
        
        # if the learned 2D and 3D wisdom files have been saved, load them. 
        # Otherwise, learn wisdom later
        Length_data2=str((rows1, cols1))
        cc2 = functions_init.load_wisdom_txt('wisdom\\'+Length_data2)
        
        Length_data3=str((frames_init, rows1, cols1))
        cc3 = functions_init.load_wisdom_txt('wisdom\\'+Length_data3)
        if cc3:
            pyfftw.import_wisdom(cc3)

        # mask for spatial filter
        mask2 = functions_init.plan_mask2(dims, (rows1, cols1), gauss_filt_size)
        # FFT planning
        (bb, bf, fft_object_b, fft_object_c) = functions_init.plan_fft3(frames_init, (rows1, cols1))
    else:
        (mask2, bf, fft_object_b, fft_object_c) = (None, None, None, None)
        bb=np.zeros((frames_init, rowspad, colspad), dtype='float32')

    # Temporal filtering preparation
    frames_initf = frames_init - leng_tf + 1
    if useTF==True:
        if prealloc:
            # past frames stored for temporal filtering
            past_frames = np.ones((leng_past, rowspad, colspad), dtype='float32')
        else:
            past_frames = np.zeros((leng_past, rowspad, colspad), dtype='float32')
    else:
        past_frames = None
    
    if prealloc: # Pre-allocate memory for some future variables
        med_frame2 = np.ones((rowspad, colspad, 2), dtype='float32')
        video_input = np.ones((frames_initf, rowspad, colspad), dtype='float32')        
        pmaps_b_init = np.ones((frames_initf, Lx, Ly), dtype='uint8')        
        frame_SNR = np.ones(dimspad, dtype='float32')
        pmaps_b = np.ones(dims, dtype='uint8')
    else:
        med_frame2 = np.zeros((rowspad, colspad, 2), dtype='float32')
        video_input = np.zeros((frames_initf, rowspad, colspad), dtype='float32')        
        pmaps_b_init = np.zeros((frames_initf, Lx, Ly), dtype='uint8')        
        frame_SNR = np.zeros(dimspad, dtype='float32')
        pmaps_b = np.zeros(dims, dtype='uint8')

    if display:
        time_init = time.time()
        print('Parameter initialization time: {} s'.format(time_init-start))


    # %% Load raw video
    h5_img = h5py.File(filename_video, 'r')
    video_raw = np.array(h5_img['mov'])
    h5_img.close()
    nframes = video_raw.shape[0]
    nframesf = nframes - leng_tf + 1
    bb[:, :Lx, :Ly] = video_raw[:frames_init]
    if display:
        time_load = time.time()
        print('Load data: {} s'.format(time_load-time_init))


    # %% Actual processing starts after the video is loaded into memory
    # Initialization using the first "frames_init" frames
    print('Initialization of algorithms using the first {} frames'.format(frames_init))
    if display:
        start_init = time.time()
    med_frame3, segs_all, recent_frames = functions_init.init_online(
        bb, dims, video_input, pmaps_b_init, fff, thresh_pmap_float, Params_post, \
        med_frame2, mask2, bf, fft_object_b, fft_object_c, Poisson_filt, \
        useSF=useSF, useTF=useTF, useSNR=useSNR, useWT=useWT, batch_size_init=batch_size_init, p=p)
    if useTF==True:
        past_frames[:leng_tf] = recent_frames
    tuple_temp = functions_online.merge_complete(segs_all[:frames_initf], dims, Params_post)

    # Initialize Online track variables
    (Masksb_temp, masks_temp, times_temp, area_temp, have_cons_temp) = tuple_temp
    # list of previously found neurons that satisfy consecutive frame requirement
    Masks_cons = functions_online.select_cons(tuple_temp) 
    # sparse matrix of previously found neurons that satisfy consecutive frame requirement
    Masks_cons_2D = sparse.vstack(Masks_cons) 
    # indices of previously found neurons that satisfy consecutive frame requirement
    ind_cons = have_cons_temp.nonzero()[0]
    segs0 = segs_all[0] # segs of initialization frames
    # segs if no neurons are found
    segs_empty = (segs0[0][0:0], segs0[1][0:0], segs0[2][0:0], segs0[3][0:0]) 
    # Number of previously found neurons that satisfy consecutive frame requirement
    N1 = len(Masks_cons)
    # list of "segs" for neurons that are not previously found
    list_segs_new = [] 
    # list of newly segmented masks for old neurons (segmented in previous frames)
    list_masks_old = [[] for _ in range(N1)] 
    # list of the newly active indices of frames of old neurons
    times_active_old = [[] for _ in range(N1)] 
    # True if the old neurons are active in the previous frame
    active_old_previous = np.zeros(N1, dtype='bool')

    if display:
        end_init = time.time()
        time_init = end_init-start_init
        time_frame_init = time_init/(frames_initf)*1000
        print('Initialization time: {:6f} s, {:6f} ms/frame'.format(time_init, time_frame_init))


    if display:
        start_online = time.time()
    # Spatial filtering preparation for online processing. 
    # Attention: this part counts to the total time
    if useSF:
        if cc2:
            pyfftw.import_wisdom(cc2)
        (bb, bf, fft_object_b, fft_object_c) = functions_init.plan_fft2((rows1, cols1))
    else:
        (bf, fft_object_b, fft_object_c) = (None, None, None)
        bb=np.zeros(dimspad, dtype='float32')

    print('Start frame by frame processing')
    # %% Online processing for the following frames
    current_frame = leng_tf
    t_merge = frames_initf
    for t in range(frames_initf, nframesf):
        if display:
            start_frame = time.time()
        # load the current frame
        bb[:Lx, :Ly] = video_raw[t+leng_tf-1]
        bb[Lx:, :] = 0
        bb[:, Ly:] = 0

        # PreProcessing
        frame_SNR = functions_online.preprocess_online(bb, dimspad, med_frame3, frame_SNR, \
            past_frames[current_frame-leng_tf:current_frame], mask2, bf, fft_object_b, fft_object_c, \
            Poisson_filt, useSF=useSF, useTF=useTF, useSNR=useSNR)

        # CNN inference
        frame_prob = functions_online.CNN_online(frame_SNR, fff, dims)

        # first step of post-processing
        segs = functions_online.postprocess_online(frame_prob, pmaps_b, thresh_pmap_float, minArea, avgArea, useWT)

        active_old = np.zeros(N1, dtype='bool') # True if the old neurons are active in the current frame
        masks_t, neuronstate_t, cents_t, areas_t = segs
        N2 = neuronstate_t.size
        if N2: # Try to merge the new masks to old neurons
            new_found = np.zeros(N2, dtype='bool')
            for n2 in range(N2):
                masks_t2 = masks_t[n2]
                cents_t2 = np.round(cents_t[n2,1]) * Ly + np.round(cents_t[n2,0])  
                # If a new masks belongs to an old neuron, the COM of the new mask must be inside the old neuron area.
                # Select possible old neurons that the new mask can merge to
                possible_masks1 = Masks_cons_2D[:,cents_t2].nonzero()[0]
                IOUs = np.zeros(len(possible_masks1))
                areas_t2 = areas_t[n2]
                for (ind,n1) in enumerate(possible_masks1):
                    # Calculate IoU and consume ratio to determine merged neurons
                    area_i = Masks_cons[n1].multiply(masks_t2).nnz
                    area_temp1 = area_temp[n1]
                    area_u = area_temp1 + areas_t2 - area_i
                    IOU = area_i / area_u
                    consume = area_i / min(area_temp1, areas_t2)
                    contain = (IOU >= thresh_IOU) or (consume >= thresh_consume)
                    if contain: # merging criterion satisfied
                        IOUs[ind] = IOU
                num_contains = IOUs.nonzero()[0].size
                if num_contains: # The new mask can merge to one of the old neurons.
                    # If there are multiple candicates, choose the one with the highest IoU
                    belongs = possible_masks1[IOUs.argmax()]
                    # merge the mask and active frame index
                    list_masks_old[belongs].append(masks_t2)
                    times_active_old[belongs].append(t + frames_initf)
                    # This old neurons is active in the current frame
                    active_old[belongs] = True 
                else: # The new mask can not merge to any old neuron.
                    new_found[n2] = True

            if np.any(new_found): # There are some new masks that can not merge to old neurons
                segs_new = (masks_t[new_found], neuronstate_t[new_found], cents_t[new_found], areas_t[new_found])
            else: # All masks already merged to old neurons
                segs_new = segs_empty
                
        else: # No neurons fould in the current frame
            segs_new = segs
        list_segs_new.append(segs_new)

        if (t + 1 - t_merge) != merge_every or t == (nframesf-1):
            # Update the old neurons with new appearances in the current frame.
            if t < (nframesf-1):
                # True if the neurons are active in the previous frame but not active in the current frame
                inactive = np.logical_and(active_old_previous, np.logical_not(active_old)).nonzero()[0]
            else: # last frame
                # All active neurons should be updated, so they are treated as inactive in the next frame
                inactive = active_old_previous.nonzero()[0]

            # Update the indicators of the previous frame using the current frame
            active_old_previous = active_old.copy()
            for n1 in inactive: 
                # merge new active frames to existing active frames for already found neurons
                # n1 is the index in the old neurons that satisfy consecutive frame requirement. 
                # n10 is the index in all old neurons.
                n10 = ind_cons[n1] 
                # Add all the new masks to the overall real-number masks
                mask_update = masks_temp[n10] + sum(list_masks_old[n1])
                masks_temp[n10] = mask_update
                # Add indices of active frames
                times_add = np.unique(np.array(times_active_old[n1]))
                times_temp[n10] = np.hstack([times_temp[n10], times_add])
                # reset lists used to store the information from new frames related to old neurons
                list_masks_old[n1] = []
                times_active_old[n1] = []
                # update the binary masks and areas
                Maskb_update = mask_update >= mask_update.max() * thresh_mask
                Masksb_temp[n10] = Maskb_update
                Masks_cons[n1] = Maskb_update
                area_temp[n10] = Maskb_update.nnz
            if inactive.size:
                Masks_cons_2D = sparse.vstack(Masks_cons) 

        if (t + 1 - t_merge) == merge_every or t == (nframesf-1):
            if t < (nframesf-1):
                # delay merging new frame to next frame by assuming all the neurons active in the previous frame
                # are still active in the current frame, to reserve merging time for new neurons
                active_old_previous = np.logical_or(active_old_previous, active_old)

            # merge new neurons with old masks that do not satisfy consecutive frame requirement
            tuple_temp = (Masksb_temp, masks_temp, times_temp, area_temp, have_cons_temp)
            # merge the remaining new masks from the most recent "merge_every" frames
            tuple_add = functions_online.merge_complete(list_segs_new, dims, Params_post)
            (Masksb_add, masks_add, times_add, area_add, have_cons_add) = tuple_add
            # update the indices of active frames
            times_add = [x + merge_every for x in times_add]
            tuple_add = (Masksb_add, masks_add, times_add, area_add, have_cons_add)
            # merge the remaining new masks with the existing masks that do not satisfy consecutive frame requirement
            tuple_temp = functions_online.merge_2_nocons(tuple_temp, tuple_add, dims, Params_post)

            (Masksb_temp, masks_temp, times_temp, area_temp, have_cons_temp) = tuple_temp
            # Update the indices of old neurons that satisfy consecutive frame requirement
            ind_cons_new = have_cons_temp.nonzero()[0]
            for (ind,ind_cons_0) in enumerate(ind_cons_new):
                if ind_cons_0 not in ind_cons: 
                    # update lists used to store the information from new frames related to old neurons
                    if ind_cons_0 > ind_cons.max():
                        list_masks_old.append([])
                        times_active_old.append([])
                    else:
                        list_masks_old.insert(ind, [])
                        times_active_old.insert(ind, [])
            
            # Update the list of previously found neurons that satisfy consecutive frame requirement
            Masks_cons = functions_online.select_cons(tuple_temp)
            Masks_cons_2D = sparse.vstack(Masks_cons) 
            N1 = len(Masks_cons)
            list_segs_new = []
            # Update whether the old neurons are active in the previous frame
            active_old_previous = np.zeros_like(have_cons_temp)
            active_old_previous[ind_cons] = active_old
            active_old_previous = active_old_previous[ind_cons_new]
            ind_cons = ind_cons_new
            t_merge += merge_every

        current_frame +=1
        # Update the stored latest frames when it runs out: move them "leng_tf" ahead
        if current_frame >= leng_past:
            current_frame = leng_tf
            past_frames[:leng_tf] = past_frames[-leng_tf:]
        if display:
            end_frame = time.time()
            list_time_per[t] = end_frame - start_frame
        if t % 1000 == 0:
            print('{} frames has been processed'.format(t))

    Masks_cons = functions_online.select_cons(tuple_temp)
    # final result. Masks_2 is a 2D sparse matrix of the segmented neurons
    if len(Masks_cons):
        Masks_2 = sparse.vstack(Masks_cons)
    else:
        Masks_2 = sparse.csc_matrix((0,dims[0]*dims[1]))

    if display:
        end_online = time.time()
        time_online = end_online-start_online
        time_frame_online = time_online/(nframesf-frames_initf)*1000
        print('Online time: {:6f} s, {:6f} ms/frame'.format(time_online, time_frame_online))

    # Save total processing time, and average processing time per frame
    if display:
        end_final = time.time()
        time_all = end_final-start_init
        time_frame_all = time_all/nframes*1000
        print('Total time: {:6f} s, {:6f} ms/frame'.format(time_all, time_frame_all))
        time_total = np.array([time_init, time_online, time_all])
        time_frame = np.array([time_frame_init, time_frame_online, time_frame_all])
    else:
        time_total = np.zeros((3,))
        time_frame = np.zeros((3,))

    # convert to a 3D array of the segmented neurons
    Masks = np.reshape(Masks_2.toarray(), (Masks_2.shape[0], Lx, Ly))
    return Masks, Masks_2, time_total, time_frame
