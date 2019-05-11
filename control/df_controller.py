# The following is an implementation of an differential flatness
# based controller. The trajectory is obtained from trajGen3D.py
# which used 7th order polynomial. The reference trajectory for all
# states and inputs is computed by dif_flat.py. Then and LQR 
# controller is used to make the quadrotor follow the reference trajectory
# generated by the differential flatness script.


# TODO:  - Finaliz uc calculation following state-space control formality
#        - Recalculate for ZXY eular rotation convention

import numpy as np
import model.params as params
from math import sin, cos

import dif_flat as dfl
import gains
from utils.utils import RPYToRot_ZYX

# LQR Translational gains and reference input matrices
Kt = np.matrix([10., 4.5825])
Nu_t = np.matrix([0.0])
Nx_t = np.matrix([[1.0],[0.0]])



# LQR Rotational gains
Kr = 2.23606
Nu_r = 0.0
Nx_r = 1.0

Kp = np.diag([gains.Kpx2, gains.Kpy2, gains.Kpz2])
Kd = np.diag([gains.Kdx2, gains.Kdy2, gains.Kdz2])
Ki = np.diag([gains.Kix2, gains.Kiy2, gains.Kiz2])

# Gains for euler angle for desired angular velocity
#       POLE PLACEMENT DESIRED POLES
# Desired pole locations for pole placement method, for more aggresive tracking
dpr = np.array([-8.0]) 
#Kr, N_ur, N_xr = gains.calculate_pp_gains(gains.Ar, gains.Br, gains.Cr, gains.D_, dpr)
Kr = 8


class memory():

    def __init__(self):
        self.freq = 5
        self.loop = 0 
        self.F = params.mass*params.g
        self.Rbw_des = np.diag([1.,1.,1.])

def run(quad, des_state):

    # obtain desired state
    # this state *must* be from a C4 differentiable trajectory
    pos_traj = des_state.pos
    vel_traj = des_state.vel
    acc_traj = des_state.acc
    jerk_traj = des_state.jerk 
    snap_traj = des_state.snap 
    yaw_traj = des_state.yaw
    yaw_dot_traj = des_state.yawdot
    yaw_ddot_traj = des_state.yawddot

    # pack everything into a point of a desired trajectory
    trajectory = [pos_traj, vel_traj, acc_traj, jerk_traj, snap_traj, yaw_traj, yaw_dot_traj, yaw_ddot_traj]

    # compute reference states and inputs from desired trajectory
    ref_ = dfl.compute_ref(trajectory)
    #print(ref_)

    # extract each reference state and inputs
    pos_ref = np.array(ref_[0])
    v_ref = np.array(ref_[1])
    or_ref = np.array(ref_[2])
    w_ref = np.array(ref_[3])

    Rbw_ref = np.array(ref_[10])
    w_dot_ref = np.array(ref_[4])
    #print("w_dot_ref: {}".format(w_dot_ref.flatten()))

    # get drone state
    pos = quad.position().reshape(3,1)
    v = quad.velocity().reshape(3,1)
    or_ = quad.attitude().reshape(3,1)  
    Rwb = RPYToRot_ZYX(or_[0][0], or_[1][0], or_[2][0])         # assumes world to body rotation
    Rbw = Rwb.T
    or_ = dfl.RotToRPY_ZYX(Rbw)                                 # assumes body to world rotation
    w = quad.omega().reshape(3,1)
    #print(pos)

    #pos = np.array([[x],[y],[z]])
    #v = np.array([[vx_r],[vy_r],[vz_r]])

    # ------------------------ #
    #  Compute thrust
    # ------------------------ #
    if(True):#(mem.loop == 0):   
        ua_e = -1.0*np.dot(Kp,pos-pos_ref) -1.0*np.dot(Kd,v-v_ref) #-1.0*np.dot(Ki,self.pos_err)  # PID control law
        
        ua_ref = np.array(ref_[5])

        ua = ua_e + ua_ref

        e_3 = np.array([[0.0],[0.0],[1.0]])  # this is z axis of body expressed in body frame
        Z_w = np.array([[0.0],[0.0],[1.0]])  # the Z axis of world frame expressed in body frame is equal to Z_b...
        wzb = np.dot(Rbw, e_3)

        F = params.mass*np.dot(wzb.T, (ua + params.g*Z_w))[0][0]
        mem.F = F
        # ------------------------ #
        #  Compute desired orientation
        # ------------------------ #
        zb_des = (ua + params.g*Z_w)/np.linalg.norm(ua + params.g*Z_w)
        yc_des = np.array(dfl.get_yc(or_ref[2][0]))   #transform to np.array 'cause comes as np.matrix
        xb_des = np.cross(yc_des, zb_des, axis=0)
        xb_des = xb_des/np.linalg.norm(xb_des)
        yb_des = np.cross(zb_des, xb_des, axis = 0)
        Rbw_des = np.concatenate((xb_des, yb_des, zb_des), axis=1)
        mem.Rbw_des = Rbw_des

        mem.loop = mem.loop +1
        #print('*********Ahora***********')
    else:
        mem.loop = mem.loop +1
        if(mem.loop == mem.freq):
            mem.loop = 0

    # ------------------------ #
    #  Compute desired angular velocity
    # ------------------------ #    
    #w_des = pucci_angular_velocity_des(Rbw, mem.Rbw_des, np.zeros((3,3)), w_ref)
    or_des = np.array(dfl.RotToRPY_ZYX(mem.Rbw_des))  # get desired roll, pitch, yaw angles
    w_des = euler_angular_velocity_des(or_, or_des, ref_[7], Kr)

    # ------------------------ #
    #  Compute control torque
    # ------------------------ # 
    #M = kai_control_torque(w, w_des, w_dot_ref, 0.17)           # gain = 0.17 from kai, allibert, hamel paper
    M = feedback_linearization_torque(w, w_des, ref_[6], Kr)

    print("F: {}\n M: {}".format(mem.F.item(0),M.flatten()))
    return mem.F.item(0), M

def pucci_angular_velocity_des(Rbw, Rbw_des, Rbw_ref_dot, w_ref):
    """
    Calculation of desired angular velocity. See:

    Pucci, D., Hamel, T., Morin, P., & Samson, C. (2014). 
    Nonlinear Feedback Control of Axisymmetric Aerial Vehicles
    https://arxiv.org/pdf/1403.5290.pdf

    Kai, J. M., Allibert, G., Hua, M. D., & Hamel, T. (2017). 
    Nonlinear feedback control of Quadrotors exploiting First-Order Drag Effects. 
    IFAC-PapersOnLine, 50(1), 8189-8195. https://doi.org/10.1016/j.ifacol.2017.08.1267
    """

    # Thrust direction is the body Z axis
    e3 = np.array([[0.0],[0.0],[1.0]])

    # extract real and desired body Z axis
    zb = np.dot(Rbw,e3)
    zb_r = np.dot(Rbw_des,e3)
    zb_r_dot = np.dot(Rbw_ref_dot, e3)

    # Calculation of desired angular velocity is done by 3 terms: an error (or feedback) term,
    # a feed-forward term and a term for the free degree of freedom of rotation around Z axis (Yaw)

    # Feedback term calculation
    k10 = 5.0
    epsilon = 0.01
    k1 = k10/(1.0 + np.dot(zb.T, zb_r)[0][0] + epsilon)
    lambda_dot = 0.0
    lambda_ = 5.0
    w_fb = (k1 + lambda_dot/lambda_)*np.cross(zb, zb_r, axis= 0)

    # Feed-forward term calculation
    w_ff = 0.0*np.cross(zb_r, zb_r_dot, axis = 0)  #np.array([[0.0],[0.0],[0.0]])

    # Yaw rotation
    w_yaw = 0.0*np.dot(w_ref.T, zb)[0][0] * zb   # np.array([[0.0],[0.0],[0.0]])

    # Convert to body frame
    w_in = np.dot(Rbw.T,w_fb + w_ff + w_yaw)

    return w_in

def euler_angular_velocity_des(euler, euler_ref, euler_dot_ref, gain):
    """
    Control law is of the form: u = K*(euler_ref - euler)
    """
    gain_matrix = np.diag([gain, gain, gain])
    euler_error = euler - euler_ref
    u = -1.0*np.dot(gain_matrix, euler_error)
    
    euler_dot = u + euler_dot_ref

    # compute w_b angular velocity commands as
    #  w_b = K.inv * uc
    #  where  (euler dot) = K*(angular_velocity)
    #  K is -not- a gain matrix, see definition below
    phi = euler[0][0]
    theta = euler[1][0]
    psi = euler[2][0]
    K = np.array([[1.0, np.sin(phi)*np.tan(theta), np.cos(phi)*np.tan(theta)],
                  [0.0, np.cos(phi), -1.0*np.sin(phi)], 
                  [0.0, np.sin(phi)/np.cos(theta), np.cos(phi)/np.cos(theta)]])

    Kinv = np.linalg.inv(K)        

    w_des = np.dot(Kinv, euler_dot)

    return w_des

def kai_control_torque(w, w_des, w_dot_ref, gain):
    K_omega = gain
    M = -K_omega*(w - w_des) + np.cross(w,np.dot(params.I,w_des), axis = 0) + np.dot(params.I, w_dot_ref)
    return np.array(M)

def feedback_linearization_torque(angular_velocity, angular_velocity_des, angular_velocity_dot_ref, gain):
    """
    Based on:
      Mclain, T., Beard, R. W., Mclain, T. ;, Beard, R. W. ;, Leishman, R. C.
      Differential Flatness Based Control of a Rotorcraft For Aggressive Maneuvers 
      (September), 2688-2693.
    """

    # angular velocity error
    w_e = angular_velocity - angular_velocity_des

    # control input ub_e for angular velocity error 
    gain_matrix = np.diag([gain, gain, gain])
    ub_e = -1.0*np.dot(gain_matrix, w_e)

    # control input ub for angular velocity
    ub = ub_e + angular_velocity_dot_ref

    # control torque M
    #print(angular_velocity)
    #print(params.I)
    M = np.dot(params.I, ub) + np.cross(angular_velocity, np.dot(params.I, angular_velocity), axis = 0)
    M = np.array(M)
    return M

mem = memory()